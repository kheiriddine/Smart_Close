import pandas as pd
import json
import re
import os
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Any, Optional
import logging

logger = logging.getLogger(__name__)

# Jours fériés France 2025
JOURS_FERIES_2025 = {
    datetime(2025, 1, 1).date(), datetime(2025, 4, 14).date(), datetime(2025, 5, 1).date(),
    datetime(2025, 5, 8).date(), datetime(2025, 5, 29).date(), datetime(2025, 6, 9).date(),
    datetime(2025, 7, 14).date(), datetime(2025, 8, 15).date(), datetime(2025, 11, 1).date(),
    datetime(2025, 11, 11).date(), datetime(2025, 12, 25).date()
}

class AnomalyDetectionWorkflow:
    """
    Workflow de détection d'anomalies pour l'analyse comptable et bancaire
    Utilise la configuration DEFAULT_ANOMALY_CONFIG d'app2.py
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialise le workflow avec une configuration
        
        Args:
            config: Configuration des seuils et paramètres de détection (DEFAULT_ANOMALY_CONFIG d'app2.py)
        """
        self.config = config
        self.alerts_counter = 1
        
    def is_weekend(self, date_obj: datetime) -> bool:
        """Vérifie si une date est un week-end"""
        return date_obj.weekday() >= 5
    
    def is_non_working_day(self, date_obj: datetime) -> bool:
        """Vérifie si une date est un jour non ouvrable (week-end ou férié)"""
        return self.is_weekend(date_obj) or date_obj.date() in JOURS_FERIES_2025
    
    def extract_reference_and_name(self, text: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Extrait la référence et le nom d'une transaction à partir du texte
        
        Args:
            text: Texte de la transaction
            
        Returns:
            Tuple (référence, nom)
        """
        if not text:
            return None, None
            
        text_clean = text.upper().replace(" ", "")
        
        # Recherche de référence facture
        fac_match = re.search(r"(FAC\d{6,})", text_clean)
        # Recherche de référence chèque
        chq_match = re.search(r"(?:CH[EÈ]QUE|CHEQUE|CHQ|N[°O]|PARCHEQUE)[:\-]?\s*(\d{5,})", text_clean)
        
        ref = fac_match.group(1) if fac_match else chq_match.group(1) if chq_match else None
        
        # Extraction du nom après tiret
        name_match = re.search(r"(?:-|–)\s*(.+)", text)
        name = name_match.group(1).strip().title() if name_match else None
        
        return ref, name
    
    def is_fees_or_maintenance(self, text: str) -> bool:
        """Détecte si une transaction est des frais ou maintenance"""
        if not text:
            return False
        text = text.lower()
        return any(kw in text for kw in ['frais', 'tenue de compte', 'cheque', 'chèque'])
    
    def parse_date(self, date_str: str) -> datetime:
        """Parse une date depuis différents formats"""
        try:
            return pd.to_datetime(date_str, dayfirst=True)
        except:
            return pd.to_datetime(date_str)
    
    def normalize_entry(self, df: pd.DataFrame, is_gl: bool = False) -> pd.DataFrame:
        """
        Normalise les entrées d'un DataFrame (relevé bancaire ou grand livre)
        
        Args:
            df: DataFrame source
            is_gl: True si c'est un grand livre, False si relevé bancaire
            
        Returns:
            DataFrame normalisé
        """
        entries = []
        
        for _, row in df.iterrows():
            try:
                if is_gl and isinstance(row['débit'], str) and 'DÉBIT' in row['débit'].upper():
                    continue
                # Parsing de la date
                date_obj = self.parse_date(row['date'])
                
                # Extraction du montant selon le type
                if is_gl:
                    debit = float(row['débit']) if pd.notnull(row['débit']) and str(row['débit']).strip() != '' else 0
                    credit = float(row['crédit']) if pd.notnull(row['crédit']) and str(row['crédit']).strip() != '' else 0
                    montant = abs(debit if debit > 0 else credit)
                else:
                    montant = abs(float(row['montant']))
                
                # Extraction de la nature/libellé
                nature = row['nature'] if not is_gl else row['libellé']
                date_str = date_obj.strftime('%d/%m/%Y')
                ref, name = self.extract_reference_and_name(nature)
                
                entries.append({
                    "date": date_str,
                    "date_obj": date_obj,
                    "montant": round(montant, 2),
                    "ref": ref,
                    "name": name,
                    "weekend": self.is_weekend(date_obj),
                    "non_ouvrable": self.is_non_working_day(date_obj),
                    "source": "GL" if is_gl else "RELEVE",
                    "raw_text": nature,
                    "is_special": self.is_fees_or_maintenance(nature),
                    "account": row.get('n° compte', '') if is_gl else '',
                    "debit": float(row['débit']) if is_gl and pd.notnull(row['débit']) and str(row['débit']).strip() != '' else 0,
                    "credit": float(row['crédit']) if is_gl and pd.notnull(row['crédit']) and str(row['crédit']).strip() != '' else 0
                })
            except Exception as e:
                logger.warning(f"Erreur ligne : {row}\n{e}")
                continue
                
        return pd.DataFrame(entries)
    
    def est_compte_concerne(self, compte: str, prefixes: List[str]) -> bool:
        """Vérifie si le compte appartient à un des préfixes donnés"""
        try:
            compte_str = str(compte).strip()
            if not compte_str:
                return False
            for prefix in prefixes:
                prefix_str = str(prefix)
                if compte_str.startswith(prefix_str):
                    return True
            return False
        except:
            return False
    
    def detect_missing_transactions(self, releve_norm: pd.DataFrame, gl_norm: pd.DataFrame, gl_all_norm: pd.DataFrame, gl_all_df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Détecte les transactions manquantes Relevé-GL avec logique améliorée en 3 étapes
        
        Étape 1 : Recherche élargie dans TOUS les comptes GL
        Étape 2 : Classification selon présence dans 512xxx
        Étape 3 : Trois types d'anomalies :
        - Vraiment manquante : Absente de tout le GL
        - Non rapprochée : Présente en 401/411/6xxx mais pas en 512xxx
        - Incohérente : Présente en 512xxx mais pas dans autres comptes
        """
        alerts = []
        
        if not self.config.get('alert_on_missing_transactions', True):
            return alerts
        
        for _, rel_tx in releve_norm.iterrows():
            if pd.isna(rel_tx['ref']) or str(rel_tx['ref']).strip() == "":
                continue
            
            ref = rel_tx['ref']
            montant = rel_tx['montant']
            
            # ÉTAPE 1 : Recherche élargie dans TOUS les comptes GL
            match_gl_all = gl_all_norm[
                (gl_all_norm['ref'] == ref) |
                (abs(gl_all_norm['montant'] - montant) <= self.config.get('amount_tolerance_absolute', 0.01))
            ]
            
            if match_gl_all.empty:
                # Transaction vraiment manquante
                alerts.append({
                    "id": self.alerts_counter,
                    "type": "OPERATION_MANQUANTE_GRAND_LIVRE",
                    "title": f"Transaction manquante dans le Grand Livre",
                    "description": f"Réf: {ref} - Montant: {montant}€ - Transaction présente dans le relevé mais absente dans le Grand Livre",
                    "source": "RELEVE",
                    "montant": montant,
                    "ref": ref,
                    "name": rel_tx['name'],
                    "date": rel_tx['date'],
                    "priority": "high" if montant > self.config.get('suspicious_amount_threshold', 50000) else "medium",
                    "commentaire": rel_tx['raw_text']
                })
                self.alerts_counter += 1
            else:
                # ÉTAPE 2 : Analyser les comptes impliqués
                mask = (gl_all_norm['ref'] == ref) | (abs(gl_all_norm['montant'] - montant) <= self.config.get('amount_tolerance_absolute', 0.01))
                matching_indices = gl_all_norm[mask].index
                comptes_match = gl_all_df.loc[matching_indices, 'n° compte'].unique()
                
                bank_accounts = [str(acc) for acc in self.config.get('monitored_bank_accounts', ['512200'])]
                other_accounts = self.config.get('fournisseur_accounts', ['401']) + self.config.get('client_accounts', ['411']) + self.config.get('charge_accounts', ['6'])
                
                # Vérifier présence dans comptes bancaires
                in_bank_accounts = any(str(cpt).startswith(tuple(bank_accounts)) for cpt in comptes_match)
                in_other_accounts = any(str(cpt).startswith(tuple(other_accounts)) for cpt in comptes_match)
                
                # ÉTAPE 3 : Classification des anomalies
                if in_bank_accounts and not in_other_accounts:
                    # Transaction incohérente : Présente en 512xxx mais pas dans autres comptes
                    alerts.append({
                        "id": self.alerts_counter,
                        "type": "TRANSACTION_INCOHERENTE",
                        "title": f"Transaction incohérente",
                        "description": f"Réf: {ref} - Montant: {montant}€ - Présente uniquement dans les comptes bancaires sans contrepartie",
                        "source": "RELEVE",
                        "montant": montant,
                        "ref": ref,
                        "name": rel_tx['name'],
                        "date": rel_tx['date'],
                        "priority": "medium",
                        "commentaire": rel_tx['raw_text'],
                        "comptes_trouvés": list(comptes_match)
                    })
                    self.alerts_counter += 1
                elif in_other_accounts and not in_bank_accounts:
                    # Transaction non rapprochée : Présente en 401/411/6xxx mais pas en 512xxx
                    alerts.append({
                        "id": self.alerts_counter,
                        "type": "TRANSACTION_NON_RAPPROCHEE",
                        "title": f"Transaction non rapprochée",
                        "description": f"Réf: {ref} - Montant: {montant}€ - Présente dans d'autres comptes mais pas dans les comptes bancaires surveillés",
                        "source": "RELEVE",
                        "montant": montant,
                        "ref": ref,
                        "name": rel_tx['name'],
                        "date": rel_tx['date'],
                        "priority": "low",
                        "commentaire": rel_tx['raw_text'],
                        "comptes_trouvés": list(comptes_match)
                    })
                    self.alerts_counter += 1
        
        return alerts
    
    def detect_missing_invoices_in_gl(self, documents: List[Dict[str, Any]], gl_all_norm: pd.DataFrame, gl_all_df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Détecte les factures non trouvées dans GL avec logique améliorée
        
        Recherche élargie : 401xxx, 6xxx, 445xxx (TVA)
        Vérification rapprochement : Présence dans 512xxx
        Quatre types d'anomalies :
        - Facture non comptabilisée : Absente de 401/6xxx/411
        - Facture non rapprochée : Présente en 401/6xxx/411 mais pas en 512xxx
        - Facture partiellement rapprochée : Montant différent entre 401/6xxx/411 et 512xxx
        - Facture sur-rapprochée : Présente en 512xxx mais pas en 401/6xxx/411
        """
        alerts = []
        
        for doc in documents:
            if doc.get('type') != 'facture' or doc.get('status') != 'completed':
                continue
            
            processed_data = doc.get('processed_data', {})
            if not processed_data:
                continue
            
            try:
                info_payment = processed_data.get('info payment', {})
                numero_facture = info_payment.get('Numéro Facture', '').strip()
                total_ttc = float(info_payment.get('Total TTC', 0))
                
                # Classification Fournisseur/Client
                nom_client = info_payment.get('Nom du Client', '').strip()
                nom_societe = processed_data.get('Nom Societe', '').strip()
                
                # Normalisation pour comparaison
                nom_client_norm = nom_client.lower().replace(' ', '') if nom_client else ''
                nom_societe_norm = nom_societe.lower().replace(' ', '') if nom_societe else ''
                
                # Déterminer le type de facture
                if "gradiant" in nom_client_norm:
                    type_facture = "Fournisseur"
                    facture_label = "Facture Fournisseur"
                else:
                    type_facture = "Client"
                    facture_label = "Facture Client"
                
                if not numero_facture:
                    continue
                
                # Recherche élargie dans les comptes concernés
                fournisseur_accounts = self.config.get('fournisseur_accounts', ['401'])
                charge_accounts = self.config.get('charge_accounts', ['6'])
                client_accounts = self.config.get('client_accounts', ['411'])
                tva_accounts = self.config.get('tva_accounts', ['445'])
                bank_accounts = self.config.get('monitored_bank_accounts', ['512200'])
                
                all_business_accounts = fournisseur_accounts + charge_accounts + client_accounts + tva_accounts
                
                # Recherche dans les comptes métier
                business_matches = gl_all_norm[
                    (gl_all_norm['ref'] == numero_facture) |
                    (abs(gl_all_norm['montant'] - total_ttc) <= self.config.get('amount_tolerance_absolute', 0.01))
                ]
                
                if not business_matches.empty:
                    # Analyser les comptes impliqués
                    mask = (gl_all_norm['ref'] == numero_facture) | (abs(gl_all_norm['montant'] - total_ttc) <= self.config.get('amount_tolerance_absolute', 0.01))
                    matching_indices = gl_all_norm[mask].index
                    comptes_match = gl_all_df.loc[matching_indices, 'n° compte'].unique()
                    
                    in_business_accounts = any(str(cpt).startswith(tuple(all_business_accounts)) for cpt in comptes_match)
                    in_bank_accounts = any(str(cpt).startswith(tuple(bank_accounts)) for cpt in comptes_match)
                    
                    if in_business_accounts and not in_bank_accounts:
                        # Facture non rapprochée
                        alerts.append({
                            "id": self.alerts_counter,
                            "type": "FACTURE_NON_RAPPROCHEE_GL",
                            "title": f"{facture_label} non rapprochée",
                            "description": f"{facture_label} {numero_facture} - Client: {nom_client} - Montant: {total_ttc}€ - Présente dans les comptes métier mais pas rapprochée bancairement",
                            "source": "FACTURE",
                            "montant": total_ttc,
                            "ref": numero_facture,
                            "document_id": doc['id'],
                            "priority": "medium",
                            "date": datetime.now().strftime('%Y-%m-%d'),
                            "comptes_trouvés": list(comptes_match),
                            "type_facture": type_facture,
                            "nom_client": nom_client,
                            "nom_societe": nom_societe
                        })
                        self.alerts_counter += 1
                    elif in_bank_accounts and not in_business_accounts:
                        # Facture sur-rapprochée
                        alerts.append({
                            "id": self.alerts_counter,
                            "type": "FACTURE_SUR_RAPPROCHEE_GL",
                            "title": f"{facture_label} sur-rapprochée",
                            "description": f"{facture_label} {numero_facture} - Client: {nom_client} - Montant: {total_ttc}€ - Présente dans les comptes bancaires mais pas dans les comptes métier",
                            "source": "FACTURE",
                            "montant": total_ttc,
                            "ref": numero_facture,
                            "document_id": doc['id'],
                            "priority": "high",
                            "date": datetime.now().strftime('%Y-%m-%d'),
                            "comptes_trouvés": list(comptes_match),
                            "type_facture": type_facture,
                            "nom_client": nom_client,
                            "nom_societe": nom_societe
                        })
                        self.alerts_counter += 1
                    elif in_business_accounts and in_bank_accounts:
                        # Vérifier les montants pour détecter un rapprochement partiel
                        business_amounts = []
                        bank_amounts = []
                        
                        for idx in matching_indices:
                            compte = str(gl_all_df.loc[idx, 'n° compte'])
                            montant = gl_all_norm.loc[idx, 'montant']
                            
                            if any(compte.startswith(acc) for acc in all_business_accounts):
                                business_amounts.append(montant)
                            elif any(compte.startswith(acc) for acc in bank_accounts):
                                bank_amounts.append(montant)
                        
                        if business_amounts and bank_amounts:
                            total_business = sum(business_amounts)
                            total_bank = sum(bank_amounts)
                            
                else:
                    # Facture non comptabilisée
                    alerts.append({
                        "id": self.alerts_counter,
                        "type": "FACTURE_NON_COMPTABILISEE_GL",
                        "title": f"{facture_label} non comptabilisée",
                        "description": f"{facture_label} {numero_facture} - Client: {nom_client} - Montant: {total_ttc}€ - Absente des comptes métier (401/6xxx/411/445)",
                        "source": "FACTURE",
                        "montant": total_ttc,
                        "ref": numero_facture,
                        "document_id": doc['id'],
                        "priority": "high",
                        "date": datetime.now().strftime('%Y-%m-%d'),
                        "type_facture": type_facture,
                        "nom_client": nom_client,
                        "nom_societe": nom_societe
                    })
                    self.alerts_counter += 1
                    
            except Exception as e:
                logger.error(f"Erreur analyse facture {doc['id']}: {str(e)}")
        
        return alerts
    
    def extraire_info_cheque(self, processed_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extrait les informations clés d'un chèque depuis processed_data
        """
        numero_cheque = str(processed_data.get('Numéro de Chèque', '')).strip()
        montant_str = processed_data.get('Montant', '0')
        
        # Extraire le montant numérique
        montant = 0
        if montant_str:
            montant_clean = re.sub(r'[^\d,.]', '', str(montant_str))
            if montant_clean:
                try:
                    montant = float(montant_clean.replace(',', '.'))
                except:
                    montant = 0
        
        return {
            'numero_cheque': numero_cheque,
            'montant': montant,
            'banque': processed_data.get('Banque', ''),
            'emetteur': processed_data.get('Emetteur', ''),
            'destinataire': processed_data.get('Destinataire', ''),
            'date': processed_data.get('Le', ''),
            'numero_compte': processed_data.get('Numéro de Compte', '')
        }
    
    def detect_missing_checks_in_gl(self, documents: List[Dict[str, Any]], gl_all_norm: pd.DataFrame, gl_all_df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Analyse les chèques selon la logique corrigée basée sur le code Colab qui fonctionne
        Recherche émission : Comptes de sortie (6xxx, 401xxx, 411xxx)
        Recherche encaissement : Comptes bancaires (512xxx)
        Quatre types d'anomalies selon la méthode corrigée
        """
        alerts = []
        
        # Filtrer les chèques
        cheques = [doc for doc in documents if doc.get('type') == 'cheque' and doc.get('status') == 'completed']
        
        logger.info(f"=== ANALYSE DE {len(cheques)} CHÈQUES ===")
        
        if not cheques:
            logger.info("Aucun chèque à analyser")
            return alerts
        
        # Assurer que gl_all_df a les bonnes colonnes
        if gl_all_df.empty:
            logger.warning("Grand livre vide")
            return alerts
        
        # Normaliser les noms de colonnes
        gl_all_df.columns = [col.strip().lower() for col in gl_all_df.columns]
        
        # Vérifier que les colonnes nécessaires existent
        required_cols = ['n° compte', 'libellé', 'débit', 'crédit']
        missing_cols = [col for col in required_cols if col not in gl_all_df.columns]
        if missing_cols:
            logger.error(f"Colonnes manquantes dans le grand livre: {missing_cols}")
            return alerts
        
        # Filtrer les lignes d'en-tête si elles existent (comme dans Colab)
        # Supprimer les lignes où 'débit' contient 'DÉBIT' (en-têtes)
        gl_df_clean = gl_all_df.copy()
        mask_header = gl_df_clean['débit'].astype(str).str.contains('DÉBIT|Débit', case=False, na=False)
        if mask_header.any():
            gl_df_clean = gl_df_clean[~mask_header].reset_index(drop=True)
            logger.info(f"Lignes d'en-tête supprimées: {mask_header.sum()}")
        
        for doc in cheques:
            processed_data = doc.get('processed_data', {})
            if not processed_data:
                continue
            
            try:
                # Extraire les informations du chèque
                info = self.extraire_info_cheque(processed_data)
                numero_cheque = info['numero_cheque']
                montant = info['montant']
                
                if not numero_cheque:
                    logger.warning(f"Chèque {doc['id']}: Numéro manquant, ignoré")
                    continue
                
                logger.info(f"--- Chèque {doc['id']}: {numero_cheque} - Montant: {montant}€ ---")
                
                # Recherche dans les comptes d'émission (6xxx, 401xxx, 411xxx) - comme dans Colab
                ecritures_emission = gl_df_clean[
                    gl_df_clean['n° compte'].apply(lambda x: self.est_compte_concerne(x, ['6', '401', '411'])) &
                    gl_df_clean['libellé'].str.contains(numero_cheque, case=False, na=False)
                ]
                
                # Recherche dans les comptes bancaires d'encaissement (512xxx) - comme dans Colab
                ecritures_encaissement = gl_df_clean[
                    gl_df_clean['n° compte'].apply(lambda x: self.est_compte_concerne(x, ['512'])) &
                    gl_df_clean['libellé'].str.contains(numero_cheque, case=False, na=False)
                ]
                
                # Calcul des montants - exactement comme dans Colab
                montant_emis = 0
                if not ecritures_emission.empty:
                    debits = pd.to_numeric(ecritures_emission['débit'], errors='coerce').fillna(0)
                    montant_emis = float(debits.sum())
                
                montant_encaisse = 0
                if not ecritures_encaissement.empty:
                    credits = pd.to_numeric(ecritures_encaissement['crédit'], errors='coerce').fillna(0)
                    montant_encaisse = float(credits.sum())
                
                logger.info(f"  Écritures émission (6/401/411): {len(ecritures_emission)} lignes, montant: {montant_emis}€")
                logger.info(f"  Écritures encaissement (512): {len(ecritures_encaissement)} lignes, montant: {montant_encaisse}€")
                
                # Classification selon les 4 types d'anomalies - exactement comme dans Colab
                if ecritures_emission.empty and ecritures_encaissement.empty:
                    # Chèque complètement absent du GL
                    logger.info("  ❌ CHÈQUE NON COMPTABILISÉ")
                    alerts.append({
                        "id": self.alerts_counter,
                        "type": "CHEQUE_NON_COMPTABILISE_GL",
                        "title": "Chèque non comptabilisé",
                        "description": f"Chèque {numero_cheque} - Montant: {montant}€ - Absent de tout le Grand Livre",
                        "source": "CHEQUE",
                        "montant": montant,
                        "ref": numero_cheque,
                        "document_id": doc['id'],
                        "priority": "high",
                        "date": datetime.now().strftime('%Y-%m-%d')
                    })
                    self.alerts_counter += 1
                    
                elif not ecritures_emission.empty and ecritures_encaissement.empty:
                    # Chèque émis mais pas encaissé
                    logger.info("  ⚠️ CHÈQUE ÉMIS NON ENCAISSÉ")
                    alerts.append({
                        "id": self.alerts_counter,
                        "type": "CHEQUE_EMIS_NON_ENCAISSE_GL",
                        "title": "Chèque émis non encaissé",
                        "description": f"Chèque {numero_cheque} - Montant: {montant}€ - Présent dans les comptes d'émission mais pas encaissé",
                        "source": "CHEQUE",
                        "montant": montant,
                        "ref": numero_cheque,
                        "document_id": doc['id'],
                        "priority": "medium",
                        "date": datetime.now().strftime('%Y-%m-%d'),
                        "montant_emis": montant_emis
                    })
                        #"difference": float(montant_emis - montant_encaisse)
                    
                elif ecritures_emission.empty and not ecritures_encaissement.empty:
                    # Chèque encaissé mais émission non trouvée
                    logger.info("  ❌ CHÈQUE ENCAISSÉ NON ÉMIS")
                    alerts.append({
                        "id": self.alerts_counter,
                        "type": "CHEQUE_ENCAISSE_NON_EMIS_GL",
                        "title": "Chèque encaissé non émis",
                        "description": f"Chèque {numero_cheque} - Montant: {montant}€ - Présent dans les comptes bancaires mais pas d'émission correspondante",
                        "source": "CHEQUE",
                        "montant": montant,
                        "ref": numero_cheque,
                        "document_id": doc['id'],
                        "priority": "high",
                        "date": datetime.now().strftime('%Y-%m-%d'),
                        "montant_encaisse": montant_encaisse
                    })
                    self.alerts_counter += 1
                    
                elif not ecritures_emission.empty and not ecritures_encaissement.empty:
                    # Chèque présent dans les deux - vérifier cohérence des montants
                    if abs(montant_emis - montant_encaisse) > self.config.get('amount_tolerance_absolute', 0.01):
                        logger.info(f"  ⚠️ CHÈQUE INCOHÉRENT (diff: {montant_emis - montant_encaisse:.2f}€)")
                        alerts.append({
                            "id": self.alerts_counter,
                            "type": "CHEQUE_INCOHERENT_GL",
                            "title": "Chèque incohérent",
                            "description": f"Chèque {numero_cheque} - Écart: {abs(montant_emis - montant_encaisse):.2f}€ - Montants différents entre émission et encaissement",
                            "source": "CHEQUE",
                            "montant": montant,
                            "ref": numero_cheque,
                            "document_id": doc['id'],
                            "priority": "medium",
                            "date": datetime.now().strftime('%Y-%m-%d'),
                            "montant_emis": montant_emis,
                            "montant_encaisse": montant_encaisse,
                            "difference": montant_emis - montant_encaisse
                        })
                        self.alerts_counter += 1
                    else:
                        logger.info("  ✅ CHÈQUE COHÉRENT")
                    
            except Exception as e:
                logger.error(f"❌ Erreur sur chèque {doc['id']}: {str(e)}")
        
        logger.info(f"=== FIN ANALYSE CHÈQUES: {len(alerts)} anomalies détectées ===")
        return alerts
    
    def detect_duplicates(self, releve_norm: pd.DataFrame, gl_norm: pd.DataFrame) -> List[Dict[str, Any]]:
        """Détecte les transactions dupliquées"""
        alerts = []
        
        if not self.config.get('alert_on_duplicate_transactions', True):
            return alerts
        
        for source_df, label in [(releve_norm, "RELEVE"), (gl_norm, "GL")]:
            # Filtrer les lignes avec ref non nulle
            df_filtered = source_df[pd.notnull(source_df['ref']) & (source_df['ref'].astype(str).str.strip() != "")]
            
            # Trouver les doublons
            duplicated_mask = df_filtered.duplicated(subset=['montant', 'ref'], keep=False)
            df_dups = df_filtered[duplicated_mask]
            df_unique_dups = df_dups.drop_duplicates(subset=['montant', 'ref'], keep='first')
            
            for _, row in df_unique_dups.iterrows():
                alerts.append({
                    "id": self.alerts_counter,
                    "type": f"DOUBLON_{label}",
                    "title": f"Transaction dupliquée dans {label}",
                    "description": f"Réf: {row['ref']} - Montant: {row['montant']}€ - Transaction présente plusieurs fois",
                    "source": label,
                    "montant": row['montant'],
                    "ref": row['ref'],
                    "date": row['date'],
                    "priority": "medium"
                })
                self.alerts_counter += 1
        
        return alerts
    
    def detect_weekend_transactions(self, releve_norm: pd.DataFrame, gl_norm: pd.DataFrame) -> List[Dict[str, Any]]:
        """Détecte les transactions effectuées un jour non ouvrable dans le relevé bancaire (RL) ou le grand livre (GL)"""
        alerts = []
    
        if not self.config.get('alert_on_weekend_transactions', True):
            return alerts
    
        # Fusion des deux sources pour détection globale
        non_ouvrables = pd.concat([releve_norm, gl_norm])
        non_ouvrables = non_ouvrables[non_ouvrables['non_ouvrable']]
    
        for _, row in non_ouvrables.iterrows():
            source_label = "RL" if row['source'] == 'releve' else "GL"
        
            alerts.append({
		    "id": self.alerts_counter,
		    "type": "TRANSACTION_JOUR_NON_OUVRABLE",
		    "title": f"Transaction sur jour non ouvrable dans {source_label}",
		    "description": f"Réf: {row['ref']} - Montant: {row['montant']}€ - Transaction un jour non ouvrable dans {source_label}",
		    "source": row['source'],
		    "montant": row['montant'],
		    "ref": row['ref'],
		    "date": row['date'],
		    "priority": "low",
		    "commentaire": row['raw_text']
            })
            self.alerts_counter += 1
    
        return alerts

    
    def detect_large_transactions(self, releve_norm: pd.DataFrame, gl_norm: pd.DataFrame) -> List[Dict[str, Any]]:
        """Détecte les transactions de montants élevés"""
        alerts = []
        
        if not self.config.get('alert_on_large_transactions', True):
            return alerts
        
        seuil = self.config.get('suspicious_amount_threshold', 50000)
        all_tx = pd.concat([releve_norm, gl_norm], ignore_index=True)
        grosses = all_tx[(all_tx['montant'] > seuil) & (all_tx['ref'].notnull()) & (all_tx['ref'] != '')]
        
        for _, row in grosses.iterrows():
            priority = "high" if row['montant'] > self.config.get('critical_amount_threshold', 10000) else "medium"
            alerts.append({
                "id": self.alerts_counter,
                "type": "TRANSACTION_MONTANT_ELEVE",
                "title": f"Transaction de montant élevé",
                "description": f"Réf: {row['ref']} - Montant: {row['montant']}€ - Montant supérieur au seuil de surveillance",
                "source": row['source'],
                "montant": row['montant'],
                "ref": row['ref'],
                "date": row['date'],
                "priority": priority,
                "commentaire": row['raw_text']
            })
            self.alerts_counter += 1
        
        return alerts
    
    def detect_amount_date_discrepancies(self, releve_norm: pd.DataFrame, gl_norm: pd.DataFrame) -> List[Dict[str, Any]]:
        """Détecte les écarts de montants et de dates"""
        alerts = []
        
        seen_refs = set()
        
        for _, rel_tx in releve_norm.iterrows():
            ref = rel_tx['ref']
            name = rel_tx['name']
            
            # Ne traiter que si ref et name sont présents
            if not ref or not name or ref in seen_refs:
                continue
            seen_refs.add(ref)
            
            matched_gl = gl_norm[gl_norm['ref'] == ref]
            if matched_gl.empty:
                continue
            
            for _, gl_tx in matched_gl.iterrows():
                delta_days = abs((rel_tx['date_obj'] - gl_tx['date_obj']).days)
                delta_amount = abs(rel_tx['montant'] - gl_tx['montant'])
                
                # Écart de date
                if self.config.get('alert_on_date_discrepancy', True):
                    if delta_days > self.config.get('max_date_delay_days', 30):
                        priority = "high" if delta_days > self.config.get('high_priority_delay_days', 15) else "medium"
                        alerts.append({
                            "id": self.alerts_counter,
                            "type": "ECART_DATE",
                            "title": f"Écart de date important",
                            "description": f"Réf: {ref} - Écart de {delta_days} jours entre GL et Relevé",
                            "source": "RELEVE",
                            "ref": ref,
                            "montant": rel_tx['montant'],
                            "delta_jours": int(delta_days),
                            "date_releve": rel_tx['date'],
                            "date_gl": gl_tx['date'],
                            "priority": priority,
                            "commentaire": gl_tx['raw_text'],
                            "name": name
                        })
                        self.alerts_counter += 1
                
                # Écart de montant
                if self.config.get('alert_on_amount_discrepancy', True):
                    seuil = max(
                        self.config.get('amount_tolerance_absolute', 0.01),
                        self.config.get('amount_tolerance_percentage', 0.01) * abs(rel_tx['montant'])
                    )
                    if delta_amount > seuil:
                        alerts.append({
                            "id": self.alerts_counter,
                            "type": "ECART_MONTANT",
                            "title": f"Écart de montant",
                            "description": f"Réf: {ref} - Écart de {delta_amount:.2f}€ entre GL et Relevé",
                            "source": "RELEVE",
                            "ref": ref,
                            "montant_releve": rel_tx['montant'],
                            "montant_gl": gl_tx['montant'],
                            "delta": float(round(delta_amount, 2)),
                            "date": rel_tx['date'],
                            "priority": "medium",
                            "name": name,
                            "commentaire": gl_tx['raw_text']
                        })
                        self.alerts_counter += 1
        
        return alerts
    
    def _analyze_facture(self, doc: Dict[str, Any], processed_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Analyse une facture spécifique"""
        alerts = []
        
        try:
            # Extraire les informations de la facture
            info_payment = processed_data.get('info payment', {})
            numero_facture = info_payment.get('Numéro Facture', '').strip()
            total_ttc = float(info_payment.get('Total TTC', 0))
            
            if not numero_facture:
                alerts.append({
                    "id": self.alerts_counter,
                    "type": "FACTURE_NUMERO_MANQUANT",
                    "title": "Numéro de facture manquant",
                    "description": f"Facture {doc['name']} sans numéro identifiable",
                    "source": "FACTURE",
                    "document_id": doc['id'],
                    "priority": "medium",
                    "date": datetime.now().strftime('%Y-%m-%d')
                })
                self.alerts_counter += 1
            
            if total_ttc > self.config.get('suspicious_amount_threshold', 50000):
                alerts.append({
                    "id": self.alerts_counter,
                    "type": "FACTURE_MONTANT_ELEVE",
                    "title": "Facture de montant élevé",
                    "description": f"Facture {numero_facture} - Montant: {total_ttc}€ - Montant supérieur au seuil",
                    "source": "FACTURE",
                    "montant": total_ttc,
                    "ref": numero_facture,
                    "document_id": doc['id'],
                    "priority": "high" if total_ttc > self.config.get('critical_amount_threshold', 10000) else "medium",
                    "date": datetime.now().strftime('%Y-%m-%d')
                })
                self.alerts_counter += 1
                
        except Exception as e:
            logger.error(f"Erreur analyse facture {doc['id']}: {str(e)}")
        
        return alerts
    
    def _analyze_cheque(self, doc: Dict[str, Any], processed_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Analyse un chèque spécifique"""
        alerts = []
        
        try:
            info = self.extraire_info_cheque(processed_data)
            numero_cheque = info['numero_cheque']
            montant = info['montant']
            
            if not numero_cheque:
                alerts.append({
                    "id": self.alerts_counter,
                    "type": "CHEQUE_NUMERO_MANQUANT",
                    "title": "Numéro de chèque manquant",
                    "description": f"Chèque {doc['name']} sans numéro identifiable",
                    "source": "CHEQUE",
                    "document_id": doc['id'],
                    "priority": "medium",
                    "date": datetime.now().strftime('%Y-%m-%d')
                })
                self.alerts_counter += 1
            
            if montant > self.config.get('suspicious_amount_threshold', 50000):
                alerts.append({
                    "id": self.alerts_counter,
                    "type": "CHEQUE_MONTANT_ELEVE",
                    "title": "Chèque de montant élevé",
                    "description": f"Chèque {numero_cheque} - Montant: {montant}€ - Montant supérieur au seuil",
                    "source": "CHEQUE",
                    "montant": montant,
                    "ref": numero_cheque,
                    "document_id": doc['id'],
                    "priority": "high" if montant > self.config.get('critical_amount_threshold', 10000) else "medium",
                    "date": datetime.now().strftime('%Y-%m-%d')
                })
                self.alerts_counter += 1
                
        except Exception as e:
            logger.error(f"Erreur analyse chèque {doc['id']}: {str(e)}")
        
        return alerts
    
    def analyze_factures_cheques(self, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Analyse spécifique des factures et chèques
        """
        alerts = []
        
        for doc in documents:
            if doc.get('status') != 'completed' or not doc.get('processed_data'):
                continue
            
            doc_type = doc.get('type', '')
            processed_data = doc.get('processed_data', {})
            
            if doc_type == 'facture':
                # Analyser les factures
                facture_alerts = self._analyze_facture(doc, processed_data)
                alerts.extend(facture_alerts)
            elif doc_type == 'cheque':
                # Analyser les chèques
                cheque_alerts = self._analyze_cheque(doc, processed_data)
                alerts.extend(cheque_alerts)
        
        return alerts
    
    def _calculate_risk_score(self, alerts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Calcule le score de risque basé sur les alertes
        Utilise les seuils configurés dans DEFAULT_ANOMALY_CONFIG
        """
        if not alerts:
            return {'score': 0, 'niveau': 'AUCUN RISQUE'}
        
        score = 0
        for alert in alerts:
            priority = alert.get('priority', 'low')
            if priority == 'high':
                score += 3
            elif priority == 'medium':
                score += 1
            else:
                score += 0.5
        
        # Limiter le score à 100
        score = min(score, 100)
        
        # Déterminer le niveau basé sur la configuration
        if score >= self.config.get('critical_threshold', 80):
            niveau = 'CRITIQUE'
        elif score >= self.config.get('high_threshold', 60):
            niveau = 'ÉLEVÉ'
        elif score >= self.config.get('medium_threshold', 30):
            niveau = 'MOYEN'
        elif score >= self.config.get('low_threshold', 10):
            niveau = 'FAIBLE'
        else:
            niveau = 'TRÈS FAIBLE'
        
        return {'score': int(score), 'niveau': niveau}
    
    def get_alerts_for_documents(self, documents: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Point d'entrée principal pour générer toutes les alertes basées sur les documents
        
        Args:
            documents: Liste des documents de la base de données
            
        Returns:
            Tuple (alertes, score_risque)
        """
        self.alerts_counter = 1
        all_alerts = []
        
        try:
            # Analyser les factures et chèques directement
            facture_cheque_alerts = self.analyze_factures_cheques(documents)
            all_alerts.extend(facture_cheque_alerts)
            
            # Rechercher les fichiers de relevé bancaire et grand livre
            releve_files = []
            gl_files = []
            
            for doc in documents:
                if doc.get('status') == 'completed' and doc.get('output_path'):
                    doc_type = doc.get('type', '')
                    if doc_type == 'releve':
                        releve_files.append(doc)
                    elif doc_type == 'grandlivre':
                        gl_files.append(doc)
            
            # Si on a des relevés et des grands livres, effectuer l'analyse de rapprochement
            if releve_files and gl_files:
                rapprochement_alerts = self._analyze_rapprochement(releve_files, gl_files, documents)
                all_alerts.extend(rapprochement_alerts)
            
            # Calculer le score de risque
            score_risque = self._calculate_risk_score(all_alerts)
            
            logger.info(f"Workflow terminé: {len(all_alerts)} alertes générées avec score de risque {score_risque['score']} ({score_risque['niveau']})")
            
            return all_alerts, score_risque
            
        except Exception as e:
            logger.error(f"Erreur dans get_alerts_for_documents: {str(e)}")
            # Retourner au moins les alertes de factures/chèques en cas d'erreur
            score_risque = self._calculate_risk_score(all_alerts)
            return all_alerts, score_risque
    
    def _analyze_rapprochement(self, releve_files: List[Dict[str, Any]], gl_files: List[Dict[str, Any]], documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Effectue l'analyse de rapprochement entre relevés bancaires et grand livre
        Inclut maintenant les nouvelles analyses pour factures et chèques
        """
        alerts = []
        
        try:
            # Charger le premier relevé et grand livre disponibles
            releve_data = None
            gl_data = None
            
            for releve_file in releve_files:
                if os.path.exists(releve_file['output_path']):
                    with open(releve_file['output_path'], 'r', encoding='utf-8') as f:
                        releve_data = json.load(f)
                    break
            
            for gl_file in gl_files:
                if os.path.exists(gl_file['output_path']):
                    with open(gl_file['output_path'], 'r', encoding='utf-8') as f:
                        gl_data = json.load(f)
                    break
            
            if not releve_data or not gl_data:
                return alerts
            
            # Normaliser les données
            releve_df = pd.DataFrame(releve_data.get("operations", []))
            gl_all_df = pd.DataFrame(gl_data.get("ecritures_comptables", []))
            
            if releve_df.empty or gl_all_df.empty:
                return alerts
            
            # Nettoyer les colonnes du GL
            gl_all_df.columns = [col.strip().lower() for col in gl_all_df.columns]
            
            # Filtrer le GL pour les comptes bancaires surveillés
            bank_accounts = self.config.get('monitored_bank_accounts', ['512200'])
            gl_bank_df = gl_all_df[gl_all_df['n° compte'].apply(lambda x: self.est_compte_concerne(x, bank_accounts))]
            
            # Normaliser les entrées
            releve_norm = self.normalize_entry(releve_df)
            gl_norm = self.normalize_entry(gl_bank_df, is_gl=True)
            gl_all_norm = self.normalize_entry(gl_all_df, is_gl=True)
            
            # Effectuer les différentes analyses
            if not releve_norm.empty and not gl_all_norm.empty:
                # 1. Transactions manquantes Relevé-GL (CORRIGÉE)
                #missing_alerts = self.detect_missing_transactions(releve_norm, gl_norm, gl_all_norm, gl_all_df)
                #alerts.extend(missing_alerts)
                
                # 2. Factures non trouvées dans GL (CORRIGÉE)
                invoice_alerts = self.detect_missing_invoices_in_gl(documents, gl_all_norm, gl_all_df)
                alerts.extend(invoice_alerts)
                
                # 3. Chèques non trouvés dans GL (CORRIGÉE AVEC LA MÉTHODE COLAB)
                check_alerts = self.detect_missing_checks_in_gl(documents, gl_all_norm, gl_all_df)
                alerts.extend(check_alerts)
                
                # Analyses existantes
                duplicate_alerts = self.detect_duplicates(releve_norm, gl_norm)
                alerts.extend(duplicate_alerts)
                
                weekend_alerts = self.detect_weekend_transactions(releve_norm, gl_norm)
                alerts.extend(weekend_alerts)
                
                large_alerts = self.detect_large_transactions(releve_norm, gl_norm)
                alerts.extend(large_alerts)
                
                discrepancy_alerts = self.detect_amount_date_discrepancies(releve_norm, gl_norm)
                alerts.extend(discrepancy_alerts)
                
        except Exception as e:
            logger.error(f"Erreur dans l'analyse de rapprochement: {str(e)}")
        
        return alerts
