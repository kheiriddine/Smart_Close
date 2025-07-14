import pandas as pd
import json
import os
import re
import glob
from datetime import datetime, timedelta
import random
from collections import Counter
import math
import logging

logger = logging.getLogger(__name__)

# --- Jours fériés France 2025 ---
jours_feries_2025 = {
    datetime(2025, 1, 1).date(), datetime(2025, 4, 14).date(), datetime(2025, 5, 1).date(),
    datetime(2025, 5, 8).date(), datetime(2025, 5, 29).date(), datetime(2025, 6, 9).date(),
    datetime(2025, 7, 14).date(), datetime(2025, 8, 15).date(), datetime(2025, 11, 1).date(),
    datetime(2025, 11, 11).date(), datetime(2025, 12, 25).date()
}

# --- Configuration par défaut des anomalies ---
DEFAULT_ANOMALY_CONFIG = {
    'max_date_delay_days': 30,
    'high_priority_delay_days': 15,
    'medium_priority_delay_days': 30,
    'amount_tolerance_percentage': 0.01,
    'amount_tolerance_absolute': 0.01,
    'critical_amount_threshold': 10000,
    'suspicious_amount_threshold': 50000,
    'alert_on_missing_transactions': True,
    'alert_on_duplicate_transactions': True,
    'alert_on_amount_discrepancy': True,
    'alert_on_date_discrepancy': True,
    'alert_on_unmatched_transactions': True,
    'alert_on_weekend_transactions': True,
    'alert_on_large_transactions': True,
    'alert_on_unexpected_balances': True,
    'monitored_bank_accounts': ['512200', '512100', '512300'],
    'critical_threshold': 10,
    'high_threshold': 5,
    'medium_threshold': 3,
    'low_threshold': 1
}

# --- Fonctions utilitaires ---
def is_weekend(date_obj): 
    """Vérifie si la date est un weekend"""
    return date_obj.weekday() >= 5

def is_non_working_day(date_obj): 
    """Vérifie si la date est un jour non ouvrable (weekend ou férié)"""
    return is_weekend(date_obj) or date_obj.date() in jours_feries_2025

def extract_reference_and_name(text):
    """Extrait la référence et le nom depuis un texte de transaction"""
    if not text:
        return None, None
        
    text_clean = text.upper().replace(" ", "")
    fac_match = re.search(r"(FAC\d{6,})", text_clean)
    chq_match = re.search(r"(?:CH[EÈ]QUE|CHEQUE|CHQ|N[°O]|PARCHEQUE)[:\-]?\s*(\d{5,})", text_clean)
    ref = fac_match.group(1) if fac_match else chq_match.group(1) if chq_match else None
    name_match = re.search(r"(?:-|–)\s*(.+)", text)
    name = name_match.group(1).strip().title() if name_match else None
    return ref, name

def is_fees_or_maintenance(text):
    """Vérifie si le texte indique des frais ou maintenance"""
    if not text: 
        return False
    text = text.lower()
    return any(kw in text for kw in ['frais', 'tenue de compte', 'cheque', 'chèque'])

def parse_date(d):
    """Parse une date avec différents formats"""
    try: 
        return pd.to_datetime(d, dayfirst=True)
    except: 
        return pd.to_datetime(d)

def clean_numeric_column(series):
    """Nettoie une colonne numérique (supprime les caractères non numériques)"""
    try:
        # Convertir en string et nettoyer
        cleaned = series.astype(str).str.replace(',', '.').str.replace('€', '').str.replace(' ', '').str.strip()
        # Remplacer les valeurs vides par 0
        cleaned = cleaned.replace('', '0').replace('nan', '0')
        # Convertir en numérique
        return pd.to_numeric(cleaned, errors='coerce').fillna(0.0)
    except Exception as e:
        logger.error(f"Erreur lors du nettoyage de la colonne numérique: {str(e)}")
        return pd.Series([0.0] * len(series))

def normalize_entry(df, is_gl=False):
    """Normalise les entrées d'un DataFrame (relevé ou grand livre)"""
    entries = []
    for _, row in df.iterrows():
        try:
            date_obj = parse_date(row['date'])
            
            if is_gl:
                # Pour le grand livre, utiliser débit ou crédit
                debit = float(row.get('débit', row.get('debit', 0)) or 0)
                credit = float(row.get('crédit', row.get('credit', 0)) or 0)
                montant = abs(debit if debit > 0 else credit)
                nature = row.get('libellé', row.get('libelle', ''))
            else:
                # Pour le relevé
                montant = abs(float(row['montant']))
                nature = row.get('nature', row.get('libelle', ''))
            
            date_str = date_obj.strftime('%d/%m/%Y')
            ref, name = extract_reference_and_name(nature)
            
            entries.append({
                "date": date_str,
                "date_obj": date_obj,
                "montant": round(montant, 2),
                "ref": ref,
                "name": name,
                "weekend": is_weekend(date_obj),
                "non_ouvrable": is_non_working_day(date_obj),
                "source": "GL" if is_gl else "RELEVE",
                "raw_text": nature,
                "is_special": is_fees_or_maintenance(nature),
                "debit": debit if is_gl else 0,
                "credit": credit if is_gl else 0
            })
        except Exception as e:
            logger.error(f"Erreur ligne : {row}\n{e}")
    return pd.DataFrame(entries)

class AnomalyDetectionWorkflow:
    def __init__(self, config=None):
        self.alerts = []
        self.config = config or DEFAULT_ANOMALY_CONFIG
        self.codes_couleur = {
            'ACTIVE': {'couleur': '🔴', 'description': 'Actif'},
            'VALIDE': {'couleur': '🟢', 'description': 'Validé'},
            'CORRIGE': {'couleur': '🔵', 'description': 'Corrigé'},
            'REJETE': {'couleur': '⚪', 'description': 'Rejeté'}
        }
    
    def get_alerts_for_documents(self, documents_db):
        """Génère des alertes basées sur l'analyse des documents traités"""
        alerts = []
        
        try:
            # Analyser seulement les documents traités avec succès qui ont des fichiers JSON
            completed_docs = [d for d in documents_db if d['status'] == 'completed' and d.get('output_path')]
            
            for doc in completed_docs:
                try:
                    # Charger le fichier JSON généré par l'OCR
                    if os.path.exists(doc['output_path']):
                        with open(doc['output_path'], 'r', encoding='utf-8') as f:
                            json_data = json.load(f)
                        
                        # Analyser selon le type de document
                        if doc['type'] == 'facture':
                            alerts.extend(self._analyze_facture_json(doc, json_data))
                        elif doc['type'] == 'cheque':
                            alerts.extend(self._analyze_cheque_json(doc, json_data))
                        elif doc['type'] == 'releve':
                            alerts.extend(self._analyze_releve_json(doc, json_data))
                        elif doc['type'] == 'grandlivre':
                            alerts.extend(self._analyze_grandlivre_json(doc, json_data))
                            
                except Exception as e:
                    # Alerte si le fichier JSON ne peut pas être lu
                    alerts.append({
                        'id': len(alerts) + 1,
                        'title': f'Erreur lecture JSON - {doc["name"]}',
                        'description': f'Impossible de lire le fichier JSON pour {doc["name"]}: {str(e)}',
                        'priority': 'high',
                        'type': 'error',
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'status': 'active',
                        'document_id': doc['id'],
                        'severite': 'HAUTE'
                    })
            
            # Analyser les correspondances entre documents
            alerts.extend(self._analyze_cross_document_anomalies(documents_db))
            
            # Ajouter des alertes de clôture génériques
            alerts.extend(self._generate_closure_alerts())
            
            # Calculer le score de risque
            score_risque = self.calculate_risk_score(alerts, len(documents_db))
            
            return alerts, score_risque
            
        except Exception as e:
            logger.error(f"Erreur lors de la génération des alertes: {str(e)}")
            alerts.append({
                'id': 1,
                'title': 'Erreur système',
                'description': f'Erreur lors de l\'analyse: {str(e)}',
                'priority': 'high',
                'type': 'system_error',
                'date': datetime.now().strftime('%Y-%m-%d'),
                'status': 'active'
            })
            score_risque = {'score': 0, 'niveau': 'ERREUR'}
            return alerts, score_risque

    def _analyze_cross_document_anomalies(self, documents_db):
        """Analyse les anomalies entre différents types de documents"""
        alerts = []
        
        try:
            # Séparer les documents par type
            releves = [d for d in documents_db if d['type'] == 'releve' and d['status'] == 'completed']
            grandlivres = [d for d in documents_db if d['type'] == 'grandlivre' and d['status'] == 'completed']
            cheques = [d for d in documents_db if d['type'] == 'cheque' and d['status'] == 'completed']
            factures = [d for d in documents_db if d['type'] == 'facture' and d['status'] == 'completed']
            
            # Analyser les correspondances relevé/grand livre
            if releves and grandlivres:
                alerts.extend(self._analyze_releve_grandlivre_matching(releves, grandlivres))
            
            # Analyser les correspondances chèques/grand livre
            if cheques and grandlivres:
                alerts.extend(self._analyze_cheque_grandlivre_matching(cheques, grandlivres))
            
            # Analyser les correspondances factures/grand livre
            if factures and grandlivres:
                alerts.extend(self._analyze_facture_grandlivre_matching(factures, grandlivres))
                
        except Exception as e:
            logger.error(f"Erreur lors de l'analyse croisée: {str(e)}")
            
        return alerts

    def _analyze_releve_grandlivre_matching(self, releves, grandlivres):
        """Analyse les correspondances entre relevés bancaires et grand livre"""
        alerts = []
        
        try:
            # Charger et normaliser les données des relevés
            releve_entries = pd.DataFrame()
            for releve in releves:
                if os.path.exists(releve['output_path']):
                    with open(releve['output_path'], 'r', encoding='utf-8') as f:
                        releve_data = json.load(f)
                    
                    if 'operations' in releve_data:
                        df = pd.DataFrame(releve_data['operations'])
                        if not df.empty:
                            normalized = normalize_entry(df, is_gl=False)
                            releve_entries = pd.concat([releve_entries, normalized], ignore_index=True)
            
            # Charger et normaliser les données du grand livre
            gl_entries = pd.DataFrame()
            for gl in grandlivres:
                if os.path.exists(gl['output_path']):
                    with open(gl['output_path'], 'r', encoding='utf-8') as f:
                        gl_data = json.load(f)
                    
                    ecritures = gl_data.get('ecritures', gl_data.get('lignes', []))
                    if ecritures:
                        df = pd.DataFrame(ecritures)
                        # Filtrer les comptes bancaires surveillés
                        if 'numero_compte' in df.columns:
                            df = df[df['numero_compte'].astype(str).str.startswith(tuple(self.config['monitored_bank_accounts']))]
                        if not df.empty:
                            normalized = normalize_entry(df, is_gl=True)
                            gl_entries = pd.concat([gl_entries, normalized], ignore_index=True)
            
            if not releve_entries.empty and not gl_entries.empty:
                # Analyser les transactions manquantes
                alerts.extend(self._detect_missing_transactions(releve_entries, gl_entries))
                
                # Analyser les doublons
                alerts.extend(self._detect_duplicate_transactions(releve_entries, gl_entries))
                
                # Analyser les écarts de montants et dates
                alerts.extend(self._detect_amount_date_discrepancies(releve_entries, gl_entries))
                
                # Analyser les transactions sur jours non ouvrables
                alerts.extend(self._detect_non_working_day_transactions(releve_entries, gl_entries))
                
        except Exception as e:
            logger.error(f"Erreur analyse relevé/grand livre: {str(e)}")
            
        return alerts

    def _detect_missing_transactions(self, releve_entries, gl_entries):
        """Détecte les transactions manquantes entre relevé et grand livre"""
        alerts = []
        
        if not self.config['alert_on_missing_transactions']:
            return alerts
        
        try:
            # Vérification GL → RELEVÉ
            for _, gl_tx in gl_entries.iterrows():
                match_found = False

                # Recherche par référence si elle existe
                if pd.notnull(gl_tx['ref']) and str(gl_tx['ref']).strip() != "":
                    match = releve_entries[releve_entries['ref'] == gl_tx['ref']]
                    if not match.empty:
                        match_found = True

                # Si aucun match par ref, essayer par montant
                if not match_found:
                    match = releve_entries[
                        (abs(releve_entries['montant'] - gl_tx['montant']) <= self.config['amount_tolerance_absolute'])
                    ]
                    if not match.empty:
                        match_found = True

                # Si toujours pas trouvé, créer une alerte
                if not match_found:
                    alerts.append({
                        'id': len(alerts) + 1,
                        'title': 'Transaction manquante dans le relevé bancaire',
                        'description': f'Transaction du grand livre non trouvée dans le relevé: {gl_tx["montant"]}€',
                        'priority': 'high',
                        'type': 'OPERATION_MANQUANTE_RELEVE',
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'status': 'active',
                        'severite': 'HAUTE',
                        'montant': gl_tx['montant'],
                        'ref': gl_tx['ref'],
                        'date_transaction': gl_tx['date'],
                        'source': 'GL'
                    })

            # Vérification RELEVÉ → GL
            for _, rel_tx in releve_entries.iterrows():
                if pd.notnull(rel_tx['ref']) and str(rel_tx['ref']).strip() != "":
                    match_found = False

                    # Recherche par référence
                    match = gl_entries[gl_entries['ref'] == rel_tx['ref']]
                    if not match.empty:
                        match_found = True

                    # Si aucun match par ref, essayer par montant
                    if not match_found:
                        match = gl_entries[
                            (abs(gl_entries['montant'] - rel_tx['montant']) <= self.config['amount_tolerance_absolute'])
                        ]
                        if not match.empty:
                            match_found = True

                    # Si toujours pas trouvé, créer une alerte
                    if not match_found:
                        alerts.append({
                            'id': len(alerts) + 1,
                            'title': 'Transaction manquante dans le grand livre',
                            'description': f'Transaction du relevé non trouvée dans le grand livre: {rel_tx["montant"]}€',
                            'priority': 'high',
                            'type': 'OPERATION_MANQUANTE_GRAND_LIVRE',
                            'date': datetime.now().strftime('%Y-%m-%d'),
                            'status': 'active',
                            'severite': 'HAUTE',
                            'montant': rel_tx['montant'],
                            'ref': rel_tx['ref'],
                            'date_transaction': rel_tx['date'],
                            'source': 'RELEVE'
                        })
                        
        except Exception as e:
            logger.error(f"Erreur détection transactions manquantes: {str(e)}")
            
        return alerts

    def _detect_duplicate_transactions(self, releve_entries, gl_entries):
        """Détecte les transactions en doublon"""
        alerts = []
        
        if not self.config['alert_on_duplicate_transactions']:
            return alerts
        
        try:
            for source_df, label in [(releve_entries, "RELEVE"), (gl_entries, "GL")]:
                # Filtrer les lignes avec ref non nulle et non vide
                df_filtered = source_df[pd.notnull(source_df['ref']) & (source_df['ref'].astype(str).str.strip() != "")]
                
                # Trouver les doublons
                duplicated_mask = df_filtered.duplicated(subset=['montant', 'ref'], keep=False)
                df_dups = df_filtered[duplicated_mask]
                
                # Pour chaque groupe, garder uniquement la première ligne
                df_unique_dups = df_dups.drop_duplicates(subset=['montant', 'ref'], keep='first')
                
                for _, row in df_unique_dups.iterrows():
                    alerts.append({
                        'id': len(alerts) + 1,
                        'title': f'Transaction en doublon - {label}',
                        'description': f'Transaction dupliquée détectée: {row["montant"]}€ (Ref: {row["ref"]})',
                        'priority': 'medium',
                        'type': f'DOUBLON_{label}',
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'status': 'active',
                        'severite': 'MOYENNE',
                        'montant': row['montant'],
                        'ref': row['ref'],
                        'date_transaction': row['date'],
                        'source': label
                    })
                    
        except Exception as e:
            logger.error(f"Erreur détection doublons: {str(e)}")
            
        return alerts

    def _detect_amount_date_discrepancies(self, releve_entries, gl_entries):
        """Détecte les écarts de montants et dates entre relevé et grand livre"""
        alerts = []
        
        try:
            seen_refs = set()
            for _, rel_tx in releve_entries.iterrows():
                ref = rel_tx['ref']
                name = rel_tx['name']

                # Ne traiter que les références valides et uniques
                if not ref or not name or ref in seen_refs:
                    continue
                seen_refs.add(ref)

                matched_gl = gl_entries[gl_entries['ref'] == ref]
                if matched_gl.empty:
                    continue  # Déjà traité comme transaction manquante

                for _, gl_tx in matched_gl.iterrows():
                    # Écart de date
                    if self.config['alert_on_date_discrepancy']:
                        delta_days = abs((rel_tx['date_obj'] - gl_tx['date_obj']).days)
                        if delta_days > self.config['max_date_delay_days']:
                            alerts.append({
                                'id': len(alerts) + 1,
                                'title': 'Écart de date important',
                                'description': f'Écart de {delta_days} jours entre relevé et grand livre (Ref: {ref})',
                                'priority': 'medium',
                                'type': 'SEQUENCE_ILLOGIQUE',
                                'date': datetime.now().strftime('%Y-%m-%d'),
                                'status': 'active',
                                'severite': 'MOYENNE',
                                'ref': ref,
                                'delta_jours': delta_days,
                                'date_releve': rel_tx['date'],
                                'date_gl': gl_tx['date'],
                                'montant': rel_tx['montant']
                            })

                    # Écart de montant
                    if self.config['alert_on_amount_discrepancy']:
                        delta_amount = abs(rel_tx['montant'] - gl_tx['montant'])
                        seuil = max(
                            self.config['amount_tolerance_absolute'],
                            self.config['amount_tolerance_percentage'] * abs(rel_tx['montant'])
                        )
                        if delta_amount > seuil:
                            alerts.append({
                                'id': len(alerts) + 1,
                                'title': 'Écart de montant',
                                'description': f'Écart de {delta_amount:.2f}€ entre relevé et grand livre (Ref: {ref})',
                                'priority': 'high',
                                'type': 'ECART_MONTANT',
                                'date': datetime.now().strftime('%Y-%m-%d'),
                                'status': 'active',
                                'severite': 'HAUTE',
                                'ref': ref,
                                'montant_releve': rel_tx['montant'],
                                'montant_gl': gl_tx['montant'],
                                'delta': round(delta_amount, 2)
                            })
                            
        except Exception as e:
            logger.error(f"Erreur détection écarts: {str(e)}")
            
        return alerts

    def _detect_non_working_day_transactions(self, releve_entries, gl_entries):
        """Détecte les transactions sur jours non ouvrables"""
        alerts = []
        
        if not self.config['alert_on_weekend_transactions']:
            return alerts
        
        try:
            non_ouvrables = pd.concat([releve_entries, gl_entries])
            non_ouvrables = non_ouvrables[non_ouvrables['non_ouvrable'] & ~non_ouvrables['is_special']]
            
            for _, row in non_ouvrables.iterrows():
                alerts.append({
                    'id': len(alerts) + 1,
                    'title': 'Transaction sur jour non ouvrable',
                    'description': f'Transaction effectuée un jour non ouvrable: {row["montant"]}€ le {row["date"]}',
                    'priority': 'medium',
                    'type': 'JOUR_NON_OUVRABLE',
                    'date': datetime.now().strftime('%Y-%m-%d'),
                    'status': 'active',
                    'severite': 'MOYENNE',
                    'montant': row['montant'],
                    'ref': row['ref'],
                    'date_transaction': row['date'],
                    'source': row['source']
                })
                
        except Exception as e:
            logger.error(f"Erreur détection jours non ouvrables: {str(e)}")
            
        return alerts

    def _analyze_cheque_grandlivre_matching(self, cheques, grandlivres):
        """Analyse les correspondances entre chèques et grand livre"""
        alerts = []
        
        try:
            # Charger les données des chèques
            cheques_data = []
            for cheque_doc in cheques:
                if os.path.exists(cheque_doc['output_path']):
                    with open(cheque_doc['output_path'], 'r', encoding='utf-8') as f:
                        cheque_json = json.load(f)
                    
                    cheque_info = self._extract_cheque_info(cheque_json, cheque_doc)
                    if cheque_info:
                        cheques_data.append(cheque_info)
            
            # Charger les données du grand livre
            gl_data = []
            for gl_doc in grandlivres:
                if os.path.exists(gl_doc['output_path']):
                    with open(gl_doc['output_path'], 'r', encoding='utf-8') as f:
                        gl_json = json.load(f)
                    
                    ecritures = gl_json.get('ecritures', gl_json.get('lignes', []))
                    gl_data.extend(ecritures)
            
            # Analyser les correspondances
            for cheque_info in cheques_data:
                correspondances = self._find_cheque_correspondances(cheque_info, gl_data)
                
                if not correspondances:
                    alerts.append({
                        'id': len(alerts) + 1,
                        'title': 'Chèque sans correspondance dans le grand livre',
                        'description': f'Chèque n°{cheque_info["numero_cheque"]} ({cheque_info["montant"]}€) non trouvé dans le grand livre',
                        'priority': 'high',
                        'type': 'CHEQUE_NON_COMPTABILISE',
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'status': 'active',
                        'severite': 'HAUTE',
                        'document_id': cheque_info['document_id'],
                        'montant': cheque_info['montant'],
                        'numero_cheque': cheque_info['numero_cheque'],
                        'beneficiaire': cheque_info.get('beneficiaire', ''),
                        'emetteur': cheque_info.get('emetteur', '')
                    })
                    
        except Exception as e:
            logger.error(f"Erreur analyse chèques/grand livre: {str(e)}")
            
        return alerts

    def _extract_cheque_info(self, cheque_json, cheque_doc):
        """Extrait les informations d'un chèque depuis le JSON"""
        try:
            return {
                'document_id': cheque_doc['id'],
                'banque': cheque_json.get('Banque', ''),
                'emetteur': cheque_json.get('Emetteur', ''),
                'beneficiaire': cheque_json.get('Destinataire', ''),
                'date': cheque_json.get('Le', ''),
                'numero_cheque': cheque_json.get('Numéro de Chèque', ''),
                'montant': float(cheque_json.get('Montant du Chèque', 0)),
                'fichier_source': cheque_doc['name']
            }
        except Exception as e:
            logger.error(f"Erreur extraction info chèque: {str(e)}")
            return None

    def _find_cheque_correspondances(self, cheque_info, gl_data):
        """Trouve les correspondances d'un chèque dans le grand livre"""
        correspondances = []
        tolerance = self.config['amount_tolerance_absolute']
        
        try:
            numero_cheque = cheque_info['numero_cheque']
            montant = cheque_info['montant']
            
            for ecriture in gl_data:
                if isinstance(ecriture, dict):
                    libelle = ecriture.get('libellé', ecriture.get('libelle', ''))
                    
                    # Recherche par numéro de chèque
                    if numero_cheque and numero_cheque in str(libelle):
                        correspondances.append(ecriture)
                        continue
                    
                    # Recherche par montant
                    if montant > 0:
                        debit = float(ecriture.get('débit', ecriture.get('debit', 0)) or 0)
                        credit = float(ecriture.get('crédit', ecriture.get('credit', 0)) or 0)
                        
                        if abs(debit - montant) <= tolerance or abs(credit - montant) <= tolerance:
                            correspondances.append(ecriture)
                            
        except Exception as e:
            logger.error(f"Erreur recherche correspondances chèque: {str(e)}")
            
        return correspondances

    def _analyze_facture_grandlivre_matching(self, factures, grandlivres):
        """Analyse les correspondances entre factures et grand livre"""
        alerts = []
        
        try:
            # Charger les données des factures
            factures_data = []
            for facture_doc in factures:
                if os.path.exists(facture_doc['output_path']):
                    with open(facture_doc['output_path'], 'r', encoding='utf-8') as f:
                        facture_json = json.load(f)
                    
                    facture_info = self._extract_facture_info(facture_json, facture_doc)
                    if facture_info:
                        factures_data.append(facture_info)
            
            # Charger les données du grand livre
            gl_data = []
            for gl_doc in grandlivres:
                if os.path.exists(gl_doc['output_path']):
                    with open(gl_doc['output_path'], 'r', encoding='utf-8') as f:
                        gl_json = json.load(f)
                    
                    ecritures = gl_json.get('ecritures', gl_json.get('lignes', []))
                    gl_data.extend(ecritures)
            
            # Analyser les correspondances
            for facture_info in factures_data:
                correspondances = self._find_facture_correspondances(facture_info, gl_data)
                
                if not correspondances:
                    alerts.append({
                        'id': len(alerts) + 1,
                        'title': 'Facture sans correspondance dans le grand livre',
                        'description': f'Facture n°{facture_info["numero_facture"]} ({facture_info["montant"]}€) non trouvée dans le grand livre',
                        'priority': 'high',
                        'type': 'FACTURE_NON_COMPTABILISEE',
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'status': 'active',
                        'severite': 'HAUTE',
                        'document_id': facture_info['document_id'],
                        'montant': facture_info['montant'],
                        'numero_facture': facture_info['numero_facture'],
                        'fournisseur': facture_info.get('fournisseur', '')
                    })
                    
        except Exception as e:
            logger.error(f"Erreur analyse factures/grand livre: {str(e)}")
            
        return alerts

    def _extract_facture_info(self, facture_json, facture_doc):
        """Extrait les informations d'une facture depuis le JSON"""
        try:
            return {
                'document_id': facture_doc['id'],
                'numero_facture': facture_json.get('numero_facture', ''),
                'fournisseur': facture_json.get('fournisseur', ''),
                'date': facture_json.get('date', ''),
                'montant': float(str(facture_json.get('montant', 0)).replace(',', '.').replace('€', '').strip() or 0),
                'fichier_source': facture_doc['name']
            }
        except Exception as e:
            logger.error(f"Erreur extraction info facture: {str(e)}")
            return None

    def _find_facture_correspondances(self, facture_info, gl_data):
        """Trouve les correspondances d'une facture dans le grand livre"""
        correspondances = []
        tolerance = self.config['amount_tolerance_absolute']
        
        try:
            numero_facture = facture_info['numero_facture']
            montant = facture_info['montant']
            
            for ecriture in gl_data:
                if isinstance(ecriture, dict):
                    libelle = ecriture.get('libellé', ecriture.get('libelle', ''))
                    
                    # Recherche par numéro de facture
                    if numero_facture and numero_facture in str(libelle):
                        correspondances.append(ecriture)
                        continue
                    
                    # Recherche par montant
                    if montant > 0:
                        debit = float(ecriture.get('débit', ecriture.get('debit', 0)) or 0)
                        credit = float(ecriture.get('crédit', ecriture.get('credit', 0)) or 0)
                        
                        if abs(debit - montant) <= tolerance or abs(credit - montant) <= tolerance:
                            correspondances.append(ecriture)
                            
        except Exception as e:
            logger.error(f"Erreur recherche correspondances facture: {str(e)}")
            
        return correspondances

    def _analyze_facture_json(self, doc, json_data):
        """Analyse le JSON d'une facture pour détecter des anomalies"""
        alerts = []
        
        try:
            # Vérifier la présence des champs obligatoires
            required_fields = ['montant', 'date', 'numero_facture', 'fournisseur']
            missing_fields = []
            
            for field in required_fields:
                if field not in json_data or not json_data[field] or json_data[field] == 'N/A':
                    missing_fields.append(field)
            
            if missing_fields:
                alerts.append({
                    'id': len(alerts) + 1,
                    'title': f'Données incomplètes - Facture {doc["name"]}',
                    'description': f'Champs manquants: {", ".join(missing_fields)}',
                    'priority': 'medium',
                    'type': 'INCOHERENCE_MONTANT_FACTURE',
                    'date': datetime.now().strftime('%Y-%m-%d'),
                    'status': 'active',
                    'document_id': doc['id'],
                    'severite': 'MOYENNE',
                    'montant': json_data.get('montant', 'N/A')
                })
            
            # Vérifier les montants suspects
            if 'montant' in json_data:
                try:
                    montant = float(str(json_data['montant']).replace(',', '.').replace('€', '').strip())
                    
                    # Montant trop élevé
                    if montant > self.config.get('suspicious_amount_threshold', 50000):
                        alerts.append({
                            'id': len(alerts) + 1,
                            'title': f'Montant élevé détecté - {doc["name"]}',
                            'description': f'Montant de {montant}€ nécessite une validation',
                            'priority': 'high',
                            'type': 'ARRONDI_SUSPECT',
                            'date': datetime.now().strftime('%Y-%m-%d'),
                            'status': 'active',
                            'document_id': doc['id'],
                            'severite': 'HAUTE',
                            'montant': montant
                        })
                    
                    # Montant rond suspect
                    if montant > 1000 and montant % 1000 == 0:
                        alerts.append({
                            'id': len(alerts) + 1,
                            'title': f'Montant rond suspect - {doc["name"]}',
                            'description': f'Montant de {montant}€ (montant rond) à vérifier',
                            'priority': 'medium',
                            'type': 'ARRONDI_SUSPECT',
                            'date': datetime.now().strftime('%Y-%m-%d'),
                            'status': 'active',
                            'document_id': doc['id'],
                            'severite': 'MOYENNE',
                            'montant': montant
                        })
                        
                except ValueError:
                    alerts.append({
                        'id': len(alerts) + 1,
                        'title': f'Format montant invalide - {doc["name"]}',
                        'description': f'Le montant "{json_data["montant"]}" n\'est pas dans un format valide',
                        'priority': 'medium',
                        'type': 'error',
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'status': 'active',
                        'document_id': doc['id'],
                        'severite': 'MOYENNE'
                    })
            
            # Vérifier les dates
            if 'date' in json_data and json_data['date'] != 'N/A':
                try:
                    # Essayer différents formats de date
                    date_formats = ['%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y']
                    date_obj = None
                    
                    for fmt in date_formats:
                        try:
                            date_obj = datetime.strptime(json_data['date'], fmt)
                            break
                        except ValueError:
                            continue
                    
                    if date_obj:
                        # Date future
                        if date_obj > datetime.now():
                            alerts.append({
                                'id': len(alerts) + 1,
                                'title': f'Date future détectée - {doc["name"]}',
                                'description': f'Date de facture dans le futur: {json_data["date"]}',
                                'priority': 'medium',
                                'type': 'SEQUENCE_ILLOGIQUE',
                                'date': datetime.now().strftime('%Y-%m-%d'),
                                'status': 'active',
                                'document_id': doc['id'],
                                'severite': 'MOYENNE'
                            })
                        
                        # Date trop ancienne (plus de 2 ans)
                        if date_obj < datetime.now() - timedelta(days=730):
                            alerts.append({
                                'id': len(alerts) + 1,
                                'title': f'Facture ancienne - {doc["name"]}',
                                'description': f'Facture datée de plus de 2 ans: {json_data["date"]}',
                                'priority': 'low',
                                'type': 'info',
                                'date': datetime.now().strftime('%Y-%m-%d'),
                                'status': 'active',
                                'document_id': doc['id'],
                                'severite': 'FAIBLE'
                            })
                            
                except ValueError:
                    alerts.append({
                        'id': len(alerts) + 1,
                        'title': f'Format date invalide - {doc["name"]}',
                        'description': f'Format de date non reconnu: {json_data["date"]}',
                        'priority': 'medium',
                        'type': 'error',
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'status': 'active',
                        'document_id': doc['id'],
                        'severite': 'MOYENNE'
                    })
                    
        except Exception as e:
            alerts.append({
                'id': len(alerts) + 1,
                'title': f'Erreur analyse facture - {doc["name"]}',
                'description': f'Erreur lors de l\'analyse: {str(e)}',
                'priority': 'medium',
                'type': 'error',
                'date': datetime.now().strftime('%Y-%m-%d'),
                'status': 'active',
                'document_id': doc['id'],
                'severite': 'MOYENNE'
            })
        
        return alerts
    
    def _analyze_cheque_json(self, doc, json_data):
        """Analyse le JSON d'un chèque pour détecter des anomalies"""
        alerts = []
        
        try:
            # Vérifier les champs obligatoires pour un chèque
            required_fields = ['montant', 'date', 'numero_cheque', 'beneficiaire']
            missing_fields = []
            
            for field in required_fields:
                if field not in json_data or not json_data[field] or json_data[field] == 'N/A':
                    missing_fields.append(field)
            
            if missing_fields:
                alerts.append({
                    'id': len(alerts) + 1,
                    'title': f'Informations chèque incomplètes - {doc["name"]}',
                    'description': f'Champs manquants: {", ".join(missing_fields)}',
                    'priority': 'high',
                    'type': 'INFORMATIONS_BANCAIRES_INCOMPLETES',
                    'date': datetime.now().strftime('%Y-%m-%d'),
                    'status': 'active',
                    'document_id': doc['id'],
                    'severite': 'HAUTE'
                })
            
            # Vérifier la cohérence montant en chiffres vs lettres
            if 'montant' in json_data and 'montant_lettres' in json_data:
                if json_data['montant'] != 'N/A' and json_data['montant_lettres'] != 'N/A':
                    alerts.append({
                        'id': len(alerts) + 1,
                        'title': f'Vérification montant chèque - {doc["name"]}',
                        'description': f'Vérifier cohérence: {json_data["montant"]} vs {json_data["montant_lettres"]}',
                        'priority': 'medium',
                        'type': 'ECART_MONTANT',
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'status': 'active',
                        'document_id': doc['id'],
                        'severite': 'MOYENNE',
                        'montant': json_data['montant']
                    })
                    
        except Exception as e:
            alerts.append({
                'id': len(alerts) + 1,
                'title': f'Erreur analyse chèque - {doc["name"]}',
                'description': f'Erreur lors de l\'analyse: {str(e)}',
                'priority': 'medium',
                'type': 'error',
                'date': datetime.now().strftime('%Y-%m-%d'),
                'status': 'active',
                'document_id': doc['id'],
                'severite': 'MOYENNE'
            })
        
        return alerts
    
    def _analyze_releve_json(self, doc, json_data):
        """Analyse le JSON d'un relevé bancaire"""
        alerts = []
        
        try:
            # Vérifier la présence des opérations
            if 'operations' in json_data:
                operations = json_data['operations']
                if isinstance(operations, list) and len(operations) > 0:
                    
                    # Analyser les opérations pour détecter des anomalies
                    for i, operation in enumerate(operations):
                        if isinstance(operation, dict):
                            # Vérifier les montants élevés
                            if 'montant' in operation:
                                try:
                                    montant = float(str(operation['montant']).replace(',', '.').replace('€', '').strip())
                                    if abs(montant) > self.config.get('critical_amount_threshold', 100000):
                                        alerts.append({
                                            'id': len(alerts) + 1,
                                            'title': f'Opération bancaire importante - {doc["name"]}',
                                            'description': f'Opération de {montant}€ nécessite une vérification',
                                            'priority': 'high',
                                            'type': 'ECART_MONTANT',
                                            'date': datetime.now().strftime('%Y-%m-%d'),
                                            'status': 'active',
                                            'document_id': doc['id'],
                                            'severite': 'HAUTE',
                                            'montant': montant
                                        })
                                except ValueError:
                                    pass
                    
                    # Vérifier le nombre d'opérations
                    if len(operations) > 100:
                        alerts.append({
                            'id': len(alerts) + 1,
                            'title': f'Volume élevé d\'opérations - {doc["name"]}',
                            'description': f'{len(operations)} opérations détectées, vérification recommandée',
                            'priority': 'medium',
                            'type': 'info',
                            'date': datetime.now().strftime('%Y-%m-%d'),
                            'status': 'active',
                            'document_id': doc['id'],
                            'severite': 'FAIBLE'
                        })
                else:
                    alerts.append({
                        'id': len(alerts) + 1,
                        'title': f'Relevé vide - {doc["name"]}',
                        'description': 'Aucune opération détectée dans le relevé',
                        'priority': 'medium',
                        'type': 'OPERATION_MANQUANTE_GRAND_LIVRE',
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'status': 'active',
                        'document_id': doc['id'],
                        'severite': 'MOYENNE'
                    })
                    
        except Exception as e:
            alerts.append({
                'id': len(alerts) + 1,
                'title': f'Erreur analyse relevé - {doc["name"]}',
                'description': f'Erreur lors de l\'analyse: {str(e)}',
                'priority': 'medium',
                'type': 'error',
                'date': datetime.now().strftime('%Y-%m-%d'),
                'status': 'active',
                'document_id': doc['id'],
                'severite': 'MOYENNE'
            })
        
        return alerts
    
    def _analyze_grandlivre_json(self, doc, json_data):
        """Analyse le JSON d'un grand livre"""
        alerts = []
        
        try:
            # Vérifier la présence des écritures
            if 'ecritures' in json_data or 'lignes' in json_data:
                ecritures = json_data.get('ecritures', json_data.get('lignes', []))
                
                if isinstance(ecritures, list) and len(ecritures) > 0:
                    
                    # Analyser les écritures
                    debit_total = 0
                    credit_total = 0
                    
                    for ecriture in ecritures:
                        if isinstance(ecriture, dict):
                            # Calculer les totaux débit/crédit
                            if 'debit' in ecriture:
                                try:
                                    debit = float(str(ecriture['debit']).replace(',', '.').replace('€', '').strip() or 0)
                                    debit_total += debit
                                except ValueError:
                                    pass
                            
                            if 'credit' in ecriture:
                                try:
                                    credit = float(str(ecriture['credit']).replace(',', '.').replace('€', '').strip() or 0)
                                    credit_total += credit
                                except ValueError:
                                    pass
                    
                    # Vérifier l'équilibre débit/crédit
                    difference = abs(debit_total - credit_total)
                    if difference > 0.01:  # Tolérance de 1 centime
                        alerts.append({
                            'id': len(alerts) + 1,
                            'title': f'Déséquilibre comptable - {doc["name"]}',
                            'description': f'Écart débit/crédit: {difference:.2f}€ (Débit: {debit_total:.2f}€, Crédit: {credit_total:.2f}€)',
                            'priority': 'high',
                            'type': 'DOUBLON_GRAND_LIVRE',
                            'date': datetime.now().strftime('%Y-%m-%d'),
                            'status': 'active',
                            'document_id': doc['id'],
                            'severite': 'HAUTE',
                            'montant': difference
                        })
                    
                    # Vérifier le volume d'écritures
                    if len(ecritures) > 1000:
                        alerts.append({
                            'id': len(alerts) + 1,
                            'title': f'Volume important d\'écritures - {doc["name"]}',
                            'description': f'{len(ecritures)} écritures détectées, contrôle approfondi recommandé',
                            'priority': 'medium',
                            'type': 'info',
                            'date': datetime.now().strftime('%Y-%m-%d'),
                            'status': 'active',
                            'document_id': doc['id'],
                            'severite': 'FAIBLE'
                        })
                        
                else:
                    alerts.append({
                        'id': len(alerts) + 1,
                        'title': f'Grand livre vide - {doc["name"]}',
                        'description': 'Aucune écriture détectée dans le grand livre',
                        'priority': 'medium',
                        'type': 'OPERATION_MANQUANTE_GRAND_LIVRE',
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'status': 'active',
                        'document_id': doc['id'],
                        'severite': 'MOYENNE'
                    })
                    
        except Exception as e:
            alerts.append({
                'id': len(alerts) + 1,
                'title': f'Erreur analyse grand livre - {doc["name"]}',
                'description': f'Erreur lors de l\'analyse: {str(e)}',
                'priority': 'medium',
                'type': 'error',
                'date': datetime.now().strftime('%Y-%m-%d'),
                'status': 'active',
                'document_id': doc['id'],
                'severite': 'MOYENNE'
            })
        
        return alerts
    
    def _generate_closure_alerts(self):
        """Génère des alertes de clôture basées sur la date actuelle"""
        alerts = []
        now = datetime.now()
        
        # Alertes de fin de mois
        if now.day > 25:
            alerts.append({
                'id': 9001,
                'title': 'Clôture mensuelle approche',
                'description': 'La clôture mensuelle approche. Vérifiez que tous les documents sont traités.',
                'priority': 'high',
                'type': 'warning',
                'date': now.strftime('%Y-%m-%d'),
                'status': 'active',
                'severite': 'HAUTE'
            })
        
        # Alertes de fin d'année
        if now.month == 12 and now.day > 15:
            alerts.append({
                'id': 9002,
                'title': 'Clôture annuelle - Préparation',
                'description': 'Préparation de la clôture annuelle. Vérification des écritures de régularisation nécessaire.',
                'priority': 'high',
                'type': 'error',
                'date': now.strftime('%Y-%m-%d'),
                'status': 'active',
                'severite': 'HAUTE'
            })
        
        # Alertes TVA
        if now.day < 20:
            alerts.append({
                'id': 9003,
                'title': 'Déclaration TVA',
                'description': f'La déclaration de TVA pour {now.strftime("%B %Y")} doit être transmise avant le 20.',
                'priority': 'medium',
                'type': 'warning',
                'date': now.strftime('%Y-%m-%d'),
                'status': 'active',
                'severite': 'MOYENNE'
            })
        
        return alerts

    def calculate_risk_score(self, alerts, total_documents):
        """Calcule un score de risque réaliste basé sur les alertes et le volume de documents"""
        if not alerts or total_documents == 0:
            return {'score': 0, 'niveau': 'FAIBLE'}
        
        # Pondération par sévérité
        severity_weights = {
            'HAUTE': 10,
            'MOYENNE': 5,
            'FAIBLE': 2
        }
        
        # Pondération par type d'anomalie
        type_weights = {
            'DOUBLON_GRAND_LIVRE': 8,
            'ARRONDI_SUSPECT': 7,
            'ECART_MONTANT': 6,
            'INCOHERENCE_MONTANT_FACTURE': 5,
            'SEQUENCE_ILLOGIQUE': 4,
            'INFORMATIONS_BANCAIRES_INCOMPLETES': 4,
            'OPERATION_MANQUANTE_GRAND_LIVRE': 3,
            'OPERATION_MANQUANTE_RELEVE': 3,
            'JOUR_NON_OUVRABLE': 2,
            'CHEQUE_NON_COMPTABILISE': 6,
            'FACTURE_NON_COMPTABILISEE': 6,
            'DOUBLON_RELEVE': 5,
            'DOUBLON_GL': 5,
            'error': 3,
            'warning': 2,
            'info': 1
        }
        
        # Calculer le score pondéré
        weighted_score = 0
        for alert in alerts:
            severity = alert.get('severite', 'FAIBLE')
            alert_type = alert.get('type', 'info')
            
            severity_weight = severity_weights.get(severity, 1)
            type_weight = type_weights.get(alert_type, 1)
            
            weighted_score += severity_weight * type_weight
        
        # Normaliser par rapport au nombre de documents
        normalized_score = weighted_score / max(total_documents, 1)
        
        # Appliquer une fonction logarithmique pour éviter les scores trop élevés
        final_score = min(100, int(30 * math.log(normalized_score + 1)))
        
        # Déterminer le niveau de risque
        if final_score >= 70:
            niveau = 'CRITIQUE'
        elif final_score >= 40:
            niveau = 'ÉLEVÉ'
        elif final_score >= 20:
            niveau = 'MOYEN'
        else:
            niveau = 'FAIBLE'
        
        return {
            'score': final_score,
            'niveau': niveau,
            'details': {
                'total_alerts': len(alerts),
                'total_documents': total_documents,
                'weighted_score': weighted_score,
                'normalized_score': normalized_score
            }
        }

    def mettre_a_jour_statut(self, alertes, index, nouveau_statut, commentaire=''):
        """Met à jour le statut d'une alerte"""
        if 0 <= index < len(alertes):
            alertes[index]['status'] = nouveau_statut.lower()
            alertes[index]['commentaire'] = commentaire
            alertes[index]['date_modification'] = datetime.now().isoformat()
        return alertes

    def generer_rapport_validation(self, alertes):
        """Génère un rapport de validation des alertes"""
        rapport = {
            'date_rapport': datetime.now().isoformat(),
            'nombre_total_alertes': len(alertes),
            'repartition_statuts': {},
            'alertes_par_severite': {}
        }
        
        # Compter par statut
        statuts = [alerte.get('status', 'active') for alerte in alertes]
        rapport['repartition_statuts'] = dict(Counter(statuts))
        
        # Compter par sévérité
        severites = [alerte.get('severite', 'FAIBLE') for alerte in alertes]
        rapport['alertes_par_severite'] = dict(Counter(severites))
        
        return rapport

# === Fonctions utilitaires pour l'analyse avancée ===

def clean_grandlivre_dataframe(df):
    """Nettoie et standardise le DataFrame du grand livre"""
    try:
        # Mapping des noms de colonnes possibles
        column_mapping = {
            'n° compte': 'numero_compte',
            'numero_compte': 'numero_compte',
            'compte': 'numero_compte',
            'libellé': 'libelle',
            'libelle': 'libelle',
            'description': 'libelle',
            'débit': 'debit',
            'debit': 'debit',
            'crédit': 'credit',
            'credit': 'credit',
            'date': 'date',
            'montant': 'montant'
        }
        
        # Renommer les colonnes
        df_clean = df.copy()
        for old_name, new_name in column_mapping.items():
            if old_name in df_clean.columns:
                df_clean = df_clean.rename(columns={old_name: new_name})
        
        # Vérifier les colonnes essentielles
        required_columns = ['numero_compte', 'debit', 'credit']
        missing_columns = [col for col in required_columns if col not in df_clean.columns]
        
        if missing_columns:
            logger.warning(f"Colonnes manquantes: {missing_columns}")
            # Créer les colonnes manquantes avec des valeurs par défaut
            for col in missing_columns:
                if col in ['debit', 'credit']:
                    df_clean[col] = 0.0
                else:
                    df_clean[col] = ''
        
        # Nettoyer les colonnes débit et crédit
        for col in ['debit', 'credit']:
            if col in df_clean.columns:
                df_clean[col] = clean_numeric_column(df_clean[col])
        
        # Nettoyer la colonne numero_compte
        if 'numero_compte' in df_clean.columns:
            df_clean['numero_compte'] = df_clean['numero_compte'].astype(str).str.strip()
        
        # Ajouter une colonne libelle si elle n'existe pas
        if 'libelle' not in df_clean.columns:
            df_clean['libelle'] = ''
        
        return df_clean
        
    except Exception as e:
        logger.error(f"Erreur lors du nettoyage du DataFrame: {str(e)}")
        return pd.DataFrame()

def calculate_account_totals(df):
    """Calcule les totaux par type de compte"""
    totals = {
        'solde_banque': 0.0,
        'creances_clients': 0.0,
        'dettes_fournisseurs': 0.0,
        'tva_deductible': 0.0,
        'tva_collectee': 0.0,
        'chiffre_affaires': 0.0,
        'charges': 0.0,
        'encaissements': 0.0
    }
    
    try:
        # Comptes bancaires (512)
        df_banque = df[df['numero_compte'].astype(str).str.startswith('512', na=False)]
        if not df_banque.empty:
            credit_512 = df_banque['credit'].sum()
            debit_512 = df_banque['debit'].sum()
            totals['solde_banque'] = float(debit_512 - credit_512)
            totals['encaissements'] = float(credit_512)
        
        # Créances clients (411)
        df_clients = df[df['numero_compte'].astype(str).str.startswith('411', na=False)]
        if not df_clients.empty:
            totals['creances_clients'] = float(df_clients['debit'].sum() - df_clients['credit'].sum())
        
        # Dettes fournisseurs (401)
        df_fournisseurs = df[df['numero_compte'].astype(str).str.startswith('401', na=False)]
        if not df_fournisseurs.empty:
            totals['dettes_fournisseurs'] = float(df_fournisseurs['credit'].sum() - df_fournisseurs['debit'].sum())
        
        # TVA déductible (4456)
        df_tva_ded = df[df['numero_compte'].astype(str).str.startswith('4456', na=False)]
        if not df_tva_ded.empty:
            totals['tva_deductible'] = float(df_tva_ded['debit'].sum())
        
        # TVA collectée (4457)
        df_tva_col = df[df['numero_compte'].astype(str).str.startswith('4457', na=False)]
        if not df_tva_col.empty:
            totals['tva_collectee'] = float(df_tva_col['credit'].sum())
        
        # Chiffre d'affaires (706)
        df_ca = df[df['numero_compte'].astype(str).str.startswith('706', na=False)]
        if not df_ca.empty:
            totals['chiffre_affaires'] = float(df_ca['credit'].sum())
        
        # Charges (comptes 6xx)
        df_charges = df[df['numero_compte'].astype(str).str.startswith('6', na=False)]
        if not df_charges.empty:
            totals['charges'] = float(df_charges['debit'].sum())
        
    except Exception as e:
        logger.error(f"Erreur lors du calcul des totaux par compte: {str(e)}")
    
    return totals

def extract_account_details(df):
    """Extrait les détails des comptes pour les dashboards spécialisés"""
    details = {
        'banque': [],
        'clients': [],
        'fournisseurs': [],
        'tva': []
    }
    
    try:
        # Comptes bancaires (512)
        df_banque = df[df['numero_compte'].astype(str).str.startswith('512', na=False)]
        for compte in df_banque['numero_compte'].unique():
            df_compte = df_banque[df_banque['numero_compte'] == compte]
            solde = float(df_compte['debit'].sum() - df_compte['credit'].sum())
            libelle = df_compte['libelle'].iloc[0] if not df_compte['libelle'].empty else f"Banque {compte}"
            details['banque'].append({
                'numero': compte,
                'libelle': libelle,
                'solde': solde
            })
        
        # Comptes clients (411)
        df_clients = df[df['numero_compte'].astype(str).str.startswith('411', na=False)]
        for compte in df_clients['numero_compte'].unique():
            df_compte = df_clients[df_clients['numero_compte'] == compte]
            solde = float(df_compte['debit'].sum() - df_compte['credit'].sum())
            libelle = df_compte['libelle'].iloc[0] if not df_compte['libelle'].empty else f"Client {compte}"
            details['clients'].append({
                'numero': compte,
                'libelle': libelle,
                'solde': solde
            })
        
        # Comptes fournisseurs (401)
        df_fournisseurs = df[df['numero_compte'].astype(str).str.startswith('401', na=False)]
        for compte in df_fournisseurs['numero_compte'].unique():
            df_compte = df_fournisseurs[df_fournisseurs['numero_compte'] == compte]
            solde = float(df_compte['credit'].sum() - df_compte['debit'].sum())
            libelle = df_compte['libelle'].iloc[0] if not df_compte['libelle'].empty else f"Fournisseur {compte}"
            details['fournisseurs'].append({
                'numero': compte,
                'libelle': libelle,
                'solde': solde
            })
        
        # Comptes TVA (445)
        df_tva = df[df['numero_compte'].astype(str).str.startswith('445', na=False)]
        for compte in df_tva['numero_compte'].unique():
            df_compte = df_tva[df_tva['numero_compte'] == compte]
            solde = float(df_compte['debit'].sum() - df_compte['credit'].sum())
            libelle = df_compte['libelle'].iloc[0] if not df_compte['libelle'].empty else f"TVA {compte}"
            details['tva'].append({
                'numero': compte,
                'libelle': libelle,
                'solde': solde
            })
        
    except Exception as e:
        logger.error(f"Erreur lors de l'extraction des détails des comptes: {str(e)}")
    
    return details

# === Fonctions principales ===

def get_alerts_for_documents(documents_db):
    """Génère des alertes basées sur l'analyse des documents traités"""
    workflow = AnomalyDetectionWorkflow()
    return workflow.get_alerts_for_documents(documents_db)

def extract_grandlivre_data(documents_db):
    """Extrait les données du grand livre des documents traités"""
    try:
        grandlivre_data = {
            'total_ecritures': 0,
            'total_debit': 0,
            'total_credit': 0,
            'comptes': {},
            'balance': 0,
            'solde_banque': 0,
            'creances_clients': 0,
            'dettes_fournisseurs': 0
        }
        
        # Analyser les documents de type grand livre
        for doc in documents_db:
            if doc.get('type') == 'grandlivre' and doc.get('status') == 'completed' and doc.get('output_path'):
                try:
                    if os.path.exists(doc['output_path']):
                        with open(doc['output_path'], 'r', encoding='utf-8') as f:
                            json_data = json.load(f)
                        
                        ecritures = json_data.get('ecritures', json_data.get('lignes', []))
                        grandlivre_data['total_ecritures'] += len(ecritures)
                        
                        for ecriture in ecritures:
                            if isinstance(ecriture, dict):
                                debit = float(ecriture.get('debit', 0) or 0)
                                credit = float(ecriture.get('credit', 0) or 0)
                                compte = str(ecriture.get('numero_compte', ''))
                                
                                grandlivre_data['total_debit'] += debit
                                grandlivre_data['total_credit'] += credit
                                
                                # Calculer les soldes par type de compte
                                if compte.startswith('512'):
                                    grandlivre_data['solde_banque'] += debit - credit
                                elif compte.startswith('411'):
                                    grandlivre_data['creances_clients'] += debit - credit
                                elif compte.startswith('401'):
                                    grandlivre_data['dettes_fournisseurs'] += credit - debit
                                
                                # Compter par compte
                                if compte not in grandlivre_data['comptes']:
                                    grandlivre_data['comptes'][compte] = {'debit': 0, 'credit': 0}
                                grandlivre_data['comptes'][compte]['debit'] += debit
                                grandlivre_data['comptes'][compte]['credit'] += credit
                        
                except Exception as e:
                    logger.error(f"Erreur lecture grand livre {doc['name']}: {str(e)}")
        
        grandlivre_data['balance'] = grandlivre_data['total_debit'] - grandlivre_data['total_credit']
        
        return grandlivre_data
        
    except Exception as e:
        logger.error(f"Erreur extraction données grand livre: {str(e)}")
        return {
            'total_ecritures': 0,
            'total_debit': 0,
            'total_credit': 0,
            'comptes': {},
            'balance': 0,
            'solde_banque': 0,
            'creances_clients': 0,
            'dettes_fournisseurs': 0
        }

def pipeline_detection_anomalies(documents_db):
    """Pipeline principal de détection d'anomalies"""
    workflow = AnomalyDetectionWorkflow()
    
    # Analyser les documents
    alertes, score_risque = workflow.get_alerts_for_documents(documents_db)
    
    return {
        'alertes': alertes,
        'score_risque': score_risque
    }

class WorkflowValidation:
    def __init__(self):
        self.codes_couleur = {
            'ACTIVE': {'couleur': '🔴', 'description': 'Actif'},
            'VALIDE': {'couleur': '🟢', 'description': 'Validé'},
            'CORRIGE': {'couleur': '🔵', 'description': 'Corrigé'},
            'REJETE': {'couleur': '⚪', 'description': 'Rejeté'}
        }
    
    def mettre_a_jour_statut(self, alertes, index, nouveau_statut, commentaire=''):
        """Met à jour le statut d'une alerte"""
        if 0 <= index < len(alertes):
            alertes[index]['status'] = nouveau_statut.lower()
            alertes[index]['commentaire'] = commentaire
            alertes[index]['date_modification'] = datetime.now().isoformat()
        return alertes

    def generer_rapport_validation(self, alertes):
        """Génère un rapport de validation des alertes"""
        rapport = {
            'date_rapport': datetime.now().isoformat(),
            'nombre_total_alertes': len(alertes),
            'repartition_statuts': {},
            'alertes_par_severite': {}
        }
        
        # Compter par statut
        statuts = [alerte.get('status', 'active') for alerte in alertes]
        rapport['repartition_statuts'] = dict(Counter(statuts))
        
        # Compter par sévérité
        severites = [alerte.get('severite', 'FAIBLE') for alerte in alertes]
        rapport['alertes_par_severite'] = dict(Counter(severites))
        
        return rapport

# === Fonctions de démonstration et génération de recommandations ===

def generer_recommandations(score_risque: dict, alertes: list) -> list:
    """Génère des recommandations basées sur l'analyse"""
    recommandations = []

    # Recommandations basées sur le score
    if score_risque['score'] >= 50:
        recommandations.append("🚨 URGENT: Score de risque très élevé - Audit complet recommandé")
    elif score_risque['score'] >= 30:
        recommandations.append("⚠️ Score de risque élevé - Vérification approfondie nécessaire")
    elif score_risque['score'] >= 15:
        recommandations.append("🔍 Score de risque moyen - Contrôles renforcés suggérés")

    # Recommandations basées sur les types d'alertes
    types_alertes = [alerte['type'] for alerte in alertes]

    if 'DOUBLON_GRAND_LIVRE' in types_alertes:
        recommandations.append("📋 Réviser les procédures de saisie comptable")

    if 'SEQUENCE_ILLOGIQUE' in types_alertes:
        recommandations.append("🔄 Vérifier les flux de traitement des écritures")

    if 'ECART_MONTANT' in types_alertes:
        recommandations.append("💰 Rapprochement bancaire à effectuer")

    if 'JOUR_NON_OUVRABLE' in types_alertes:
        recommandations.append("📅 Contrôler les autorisations d'accès aux systèmes")

    if 'ARRONDI_SUSPECT' in types_alertes:
        recommandations.append("🔍 Investigation approfondie sur les montants suspects")

    if 'OPERATION_MANQUANTE_GRAND_LIVRE' in types_alertes:
        recommandations.append("🏦 Vérifier la complétude des écritures bancaires")

    if 'OPERATION_MANQUANTE_RELEVE' in types_alertes:
        recommandations.append("🏦 Vérifier la complétude des relevés bancaires")

    if 'INCOHERENCE_MONTANT_FACTURE' in types_alertes:
        recommandations.append("📄 Contrôler la cohérence des factures OCR")

    if 'CHEQUE_NON_COMPTABILISE' in types_alertes:
        recommandations.append("📝 Vérifier la comptabilisation des chèques")

    if 'FACTURE_NON_COMPTABILISEE' in types_alertes:
        recommandations.append("📝 Vérifier la comptabilisation des factures")

    return recommandations

def exemple_complet(documents_db):
    """Exemple complet d'utilisation du workflow"""
    print("🔍 EXEMPLE COMPLET D'UTILISATION DU WORKFLOW")
    print("=" * 60)

    # Lancer l'analyse complète avec vos données réelles
    print("\n🚀 Lancement de l'analyse complète...")

    resultats = pipeline_detection_anomalies(documents_db)

    if not resultats:
        print("❌ Erreur lors de l'analyse")
        return
        
    # Analyser les résultats
    print("\n📊 ANALYSE DES RÉSULTATS")
    print("=" * 40)

    score_risque = resultats['score_risque']
    alertes = resultats['alertes']

    print(f"🎯 Score de risque global: {score_risque['score']}/100")
    print(f"⚠️ Niveau de risque: {score_risque['niveau']}")
    print(f"🔍 Nombre total d'alertes: {len(alertes)}")

    # Analyser par type d'anomalie
    types_anomalies = {}
    for alerte in alertes:
        type_alerte = alerte['type']
        if type_alerte not in types_anomalies:
            types_anomalies[type_alerte] = []
        types_anomalies[type_alerte].append(alerte)

    print(f"\n📋 Répartition des anomalies:")
    for type_anomalie, alertes_type in types_anomalies.items():
        print(f"  • {type_anomalie}: {len(alertes_type)} alertes")

    # Démonstration du workflow de validation
    print("\n🔧 DÉMONSTRATION DU WORKFLOW DE VALIDATION")
    print("=" * 50)

    workflow = WorkflowValidation()

    # Simuler la validation de quelques alertes
    if alertes:
        print("Simulation de validation d'alertes...")

        # Valider la première alerte
        if len(alertes) > 0:
            alertes = workflow.mettre_a_jour_statut(
                alertes, 0, 'VALIDE',
                'Anomalie confirmée après vérification manuelle'
            )

        # Corriger la deuxième alerte si elle existe
        if len(alertes) > 1:
            alertes = workflow.mettre_a_jour_statut(
                alertes, 1, 'CORRIGE',
                'Erreur de saisie corrigée dans le système'
            )

        # Rejeter la troisième alerte si elle existe
        if len(alertes) > 2:
            alertes = workflow.mettre_a_jour_statut(
                alertes, 2, 'REJETE',
                'Fausse alerte - opération normale'
            )

        print("✅ Statuts mis à jour pour les premières alertes")

    # Générer le rapport final
    rapport_final = workflow.generer_rapport_validation(alertes)

    print(f"\n📈 RAPPORT FINAL DE VALIDATION")
    print("=" * 35)
    print(f"Date du rapport: {rapport_final['date_rapport']}")
    print(f"Nombre total d'alertes: {rapport_final['nombre_total_alertes']}")

    print(f"\nRépartition par statut:")
    for statut, count in rapport_final['repartition_statuts'].items():
        couleur = workflow.codes_couleur.get(statut.upper(), {}).get('couleur', '⚫')
        description = workflow.codes_couleur.get(statut.upper(), {}).get('description', statut)
        print(f"  {couleur} {description}: {count} alertes")

    print(f"\nRépartition par sévérité:")
    for severite, count in rapport_final['alertes_par_severite'].items():
        print(f"  • {severite}: {count} alertes")

    # Sauvegarder le rapport final
    rapport_complet = {
        'date_analyse': datetime.now().isoformat(),
        'donnees_analysees': {
            'total_documents': len(documents_db),
            'documents_traites': len([d for d in documents_db if d['status'] == 'completed']),
            'factures_ocr': len([d for d in documents_db if d['type'] == 'facture']),
            'cheques_ocr': len([d for d in documents_db if d['type'] == 'cheque']),
            'releves_ocr': len([d for d in documents_db if d['type'] == 'releve']),
            'grandlivre_ocr': len([d for d in documents_db if d['type'] == 'grandlivre'])
        },
        'score_risque': score_risque,
        'alertes': alertes,
        'rapport_validation': rapport_final,
        'recommandations': generer_recommandations(score_risque, alertes)
    }

    return rapport_complet

def analyser_tendances_temporelles(alertes: list):
    """Analyse les tendances temporelles des anomalies"""
    print("\n📈 ANALYSE DES TENDANCES TEMPORELLES")
    print("=" * 40)

    # Extraire les dates des alertes
    dates_alertes = []
    for alerte in alertes:
        if 'date' in alerte and alerte['date'] != 'N/A':
            try:
                date_obj = datetime.strptime(alerte['date'], '%Y-%m-%d')
                dates_alertes.append(date_obj)
            except:
                continue

    if not dates_alertes:
        print("❌ Aucune date valide trouvée dans les alertes")
        return

    # Analyser la distribution
    dates_alertes.sort()

    print(f"📅 Période d'analyse: {dates_alertes[0].strftime('%d/%m/%Y')} à {dates_alertes[-1].strftime('%d/%m/%Y')}")
    print(f"📊 Nombre de dates avec anomalies: {len(set(dates_alertes))}")

    # Identifier les pics d'anomalies
    compteur_dates = Counter([date.strftime('%d/%m/%Y') for date in dates_alertes])

    print(f"\n🎯 Dates avec le plus d'anomalies:")
    for date, count in compteur_dates.most_common(5):
        print(f"  • {date}: {count} anomalies")

def afficher_alertes_par_severite(alertes: list):
    """Affiche les alertes groupées par sévérité"""
    print("\n🚨 ALERTES PAR SÉVÉRITÉ")
    print("=" * 30)

    alertes_par_severite = {'HAUTE': [], 'MOYENNE': [], 'FAIBLE': []}

    for alerte in alertes:
        severite = alerte.get('severite', 'FAIBLE')
        if severite in alertes_par_severite:
            alertes_par_severite[severite].append(alerte)

    for severite in ['HAUTE', 'MOYENNE', 'FAIBLE']:
        alertes_sev = alertes_par_severite[severite]
        if alertes_sev:
            emoji = {'HAUTE': '🔴', 'MOYENNE': '🟡', 'FAIBLE': '🟢'}[severite]
            print(f"\n{emoji} SÉVÉRITÉ {severite} ({len(alertes_sev)} alertes)")
            print("-" * 40)

            for i, alerte in enumerate(alertes_sev[:5], 1):  # Afficher les 5 premières
                print(f"{i}. {alerte.get('description', 'N/A')}")
                if 'montant' in alerte:
                    print(f"   💰 Montant: {alerte['montant']}€")
                if 'compte' in alerte:
                    print(f"   🏦 Compte: {alerte['compte']}")
                print()

            if len(alertes_sev) > 5:
                print(f"   ... et {len(alertes_sev) - 5} autres alertes")
