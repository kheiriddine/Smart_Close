import pandas as pd
import json
import os
from datetime import datetime, timedelta
import random
from collections import Counter
import math
import logging

logger = logging.getLogger(__name__)

class AnomalyDetectionWorkflow:
    def __init__(self):
        self.alerts = []
        self.codes_couleur = {
            'ACTIVE': {'couleur': '🔴', 'description': 'Actif'},
            'VALIDE': {'couleur': '🟢', 'description': 'Validé'},
            'CORRIGE': {'couleur': '🔵', 'description': 'Corrigé'},
            'REJETE': {'couleur': '⚪', 'description': 'Rejeté'}
        }
        
    def analyze_json_files(self, documents_db):
        """Analyse les fichiers JSON générés par l'OCR pour détecter des anomalies"""
        alerts = []
        
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
        
        # Ajouter des alertes de clôture génériques
        alerts.extend(self._generate_closure_alerts())
        
        return alerts
    
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
                    if montant > 50000:
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
                                    if abs(montant) > 100000:
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
            'JOUR_NON_OUVRABLE': 2,
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
        # Plus il y a de documents, plus le score est dilué
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

def clean_numeric_column(series):
    """
    Nettoie une colonne numérique (supprime les caractères non numériques)
    Basé sur votre code Colab
    """
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

def clean_grandlivre_dataframe(df):
    """
    Nettoie et standardise le DataFrame du grand livre
    """
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
        
        # Nettoyer les colonnes débit et crédit (comme dans votre Colab)
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
    """
    Calcule les totaux par type de compte selon votre logique Colab
    """
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
        # Comptes bancaires (512) - Logique de votre Colab
        df_banque = df[df['numero_compte'].astype(str).str.startswith('512', na=False)]
        if not df_banque.empty:
            credit_512 = df_banque['credit'].sum()
            debit_512 = df_banque['debit'].sum()
            # Solde bancaire = Solde de départ + crédits - débits sur le compte 512
            # Pour simplifier, on utilise debit - credit
            totals['solde_banque'] = float(debit_512 - credit_512)
            totals['encaissements'] = float(credit_512)
        
        # Créances clients (411) - Factures clients non encaissées
        df_clients = df[df['numero_compte'].astype(str).str.startswith('411', na=False)]
        if not df_clients.empty:
            # Créances = débit - crédit sur comptes clients
            totals['creances_clients'] = float(df_clients['debit'].sum() - df_clients['credit'].sum())
        
        # Dettes fournisseurs (401)
        df_fournisseurs = df[df['numero_compte'].astype(str).str.startswith('401', na=False)]
        if not df_fournisseurs.empty:
            # Dettes = crédit - débit sur comptes fournisseurs
            totals['dettes_fournisseurs'] = float(df_fournisseurs['credit'].sum() - df_fournisseurs['debit'].sum())
        
        # TVA déductible (4456) — débit
        df_tva_ded = df[df['numero_compte'].astype(str).str.startswith('4456', na=False)]
        if not df_tva_ded.empty:
            totals['tva_deductible'] = float(df_tva_ded['debit'].sum())
        
        # TVA collectée (4457) — crédit
        df_tva_col = df[df['numero_compte'].astype(str).str.startswith('4457', na=False)]
        if not df_tva_col.empty:
            totals['tva_collectee'] = float(df_tva_col['credit'].sum())
        
        # Chiffre d'affaires (706) — crédit
        df_ca = df[df['numero_compte'].astype(str).str.startswith('706', na=False)]
        if not df_ca.empty:
            totals['chiffre_affaires'] = float(df_ca['credit'].sum())
        
        # Charges (comptes 6xx) — débit
        df_charges = df[df['numero_compte'].astype(str).str.startswith('6', na=False)]
        if not df_charges.empty:
            totals['charges'] = float(df_charges['debit'].sum())
        
    except Exception as e:
        logger.error(f"Erreur lors du calcul des totaux par compte: {str(e)}")
    
    return totals

def extract_account_details(df):
    """
    Extrait les détails des comptes pour les dashboards spécialisés
    """
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


def get_alerts_for_documents(documents_db):
    """
    Génère des alertes basées sur l'analyse des documents traités
    """
    alerts = []
    alert_id = 1
    
    try:
        
        
        # Calculer le score de risque
        workflow = AnomalyDetectionWorkflow()
        
        # Analyser les documents pour générer des alertes spécifiques
        document_alerts = workflow.analyze_json_files(documents_db)
        alerts.extend(document_alerts)
        
        
        
        # Alertes sur les documents non traités
        pending_docs = [d for d in documents_db if d.get('status') == 'pending']
        if len(pending_docs) > 5:
            alerts.append({
                'id': len(alerts) + 1,
                'title': 'Documents en attente de traitement',
                'description': f'{len(pending_docs)} documents en attente de traitement OCR',
                'priority': 'low',
                'type': 'pending_documents',
                'date': datetime.now().strftime('%Y-%m-%d'),
                'status': 'active'
            })
        
        # Alertes sur les échecs de traitement
        failed_docs = [d for d in documents_db if d.get('status') == 'failed']
        if failed_docs:
            alerts.append({
                'id': len(alerts) + 1,
                'title': 'Échecs de traitement OCR',
                'description': f'{len(failed_docs)} documents ont échoué lors du traitement',
                'priority': 'medium',
                'type': 'processing_failures',
                'date': datetime.now().strftime('%Y-%m-%d'),
                'status': 'active'
            })
        
        # Calculer le score de risque
        score_risque = workflow.calculate_risk_score(alerts, len(documents_db))
        
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

def pipeline_detection_anomalies(documents_db):
    """Pipeline principal de détection d'anomalies"""
    workflow = AnomalyDetectionWorkflow()
    
    # Analyser les documents
    alertes = workflow.analyze_json_files(documents_db)
    
    # Calculer le score de risque
    score_risque = workflow.calculate_risk_score(alertes, len(documents_db))
    
    return {
        'alertes': alertes,
        'score_risque': score_risque
    }

def exemple_complet(documents_db):
    """Exemple complet d'utilisation du workflow"""
    print("🔍 EXEMPLE COMPLET D'UTILISATION DU WORKFLOW")
    print("=" * 60)

    #Lancer l'analyse complète avec vos données réelles
    print("\n🚀 Lancement de l'analyse complète...")

    resultats = pipeline_detection_anomalies(documents_db)

    if not resultats:
        print("❌ Erreur lors de l'analyse")
        return
        
    #Analyser les résultats
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

    if 'INCOHERENCE_MONTANT_FACTURE' in types_alertes:
        recommandations.append("📄 Contrôler la cohérence des factures OCR")

    return recommandations

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
