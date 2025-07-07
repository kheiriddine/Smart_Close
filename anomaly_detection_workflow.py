import pandas as pd
import json
import os
from datetime import datetime, timedelta, date
import random
from collections import Counter, defaultdict
import math
import logging
import hashlib
import glob
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger(__name__)

class AnomalyDetectionWorkflow:
    def __init__(self, config=None):
        self.alerts = []
        self.config = config or self._get_default_config()
        self.codes_couleur = {
            'ACTIVE': {'couleur': '🔴', 'description': 'Actif'},
            'VALIDE': {'couleur': '🟢', 'description': 'Validé'},
            'CORRIGE': {'couleur': '🔵', 'description': 'Corrigé'},
            'REJETE': {'couleur': '⚪', 'description': 'Rejeté'}
        }
        
        # Types d'alertes activées selon la configuration
        self.alert_types = {
            'missing_transactions': self.config.get('alert_on_missing_transactions', True),
            'duplicate_transactions': self.config.get('alert_on_duplicate_transactions', True),
            'amount_discrepancies': self.config.get('alert_on_amount_discrepancy', True),
            'date_discrepancies': self.config.get('alert_on_date_discrepancy', True),
            'unreconciled_transactions': self.config.get('alert_on_unmatched_transactions', True),
            'weekend_transactions': self.config.get('alert_on_weekend_transactions', True),
            'large_transactions': self.config.get('alert_on_large_transactions', True)
        }

    def _get_default_config(self):
        """Configuration par défaut"""
        return {
            'max_date_delay_days': 3,
            'high_priority_delay_days': 1,
            'medium_priority_delay_days': 7,
            'amount_tolerance_percentage': 2.0,
            'amount_tolerance_absolute': 5.0,
            'critical_amount_threshold': 50000,
            'suspicious_amount_threshold': 10000,
            'large_transaction_threshold': 5000,
            'weekend_transaction_alert': True,
            'critical_threshold': 80,
            'high_threshold': 60,
            'medium_threshold': 30
        }

    def analyze_json_files(self, documents_db):
        """Analyse les fichiers JSON pour détecter des anomalies avec rapprochement bancaire"""
        alerts = []
        
        # Séparer les documents par type
        bank_statements = [d for d in documents_db if d['type'] == 'releve' and d['status'] == 'completed']
        ledger_docs = [d for d in documents_db if d['type'] == 'grandlivre' and d['status'] == 'completed']
        facture_docs = [d for d in documents_db if d['type'] == 'facture' and d['status'] == 'completed']
        cheque_docs = [d for d in documents_db if d['type'] == 'cheque' and d['status'] == 'completed']
        
        # Analyser chaque document individuellement
        completed_docs = [d for d in documents_db if d['status'] == 'completed' and d.get('output_path')]
        
        for doc in completed_docs:
            try:
                if os.path.exists(doc['output_path']):
                    with open(doc['output_path'], 'r', encoding='utf-8') as f:
                        json_data = json.load(f)
                    
                    if doc['type'] == 'facture':
                        alerts.extend(self._analyze_facture_json(doc, json_data))
                    elif doc['type'] == 'cheque':
                        alerts.extend(self._analyze_cheque_json(doc, json_data))
                    elif doc['type'] == 'releve':
                        alerts.extend(self._analyze_releve_json(doc, json_data))
                    elif doc['type'] == 'grandlivre':
                        alerts.extend(self._analyze_grandlivre_json(doc, json_data))
                        
            except Exception as e:
                alerts.append(self._create_alert(
                    f'Erreur lecture JSON - {doc["name"]}',
                    f'Impossible de lire le fichier JSON pour {doc["name"]}: {str(e)}',
                    'high', 'error', doc['id'], 'HAUTE', doc["name"]
                ))
        
        # Rapprochements spécialisés
        if bank_statements and ledger_docs:
            alerts.extend(self._perform_bank_ledger_reconciliation(bank_statements, ledger_docs))
        
        if facture_docs and ledger_docs:
            alerts.extend(self._perform_facture_ledger_reconciliation(facture_docs, ledger_docs))
            
        if cheque_docs and ledger_docs:
            alerts.extend(self._perform_cheque_ledger_reconciliation(cheque_docs, ledger_docs))
        
        # Ajouter des alertes de clôture si nécessaire
        if completed_docs:
            alerts.extend(self._generate_closure_alerts())
        
        return alerts

    def _perform_bank_ledger_reconciliation(self, bank_statements, ledger_docs):
        """Effectue le rapprochement entre relevés bancaires et grand livre (compte 512200)"""
        alerts = []
        
        try:
            # Extraire les transactions des relevés bancaires
            bank_transactions = self._extract_bank_transactions_improved(bank_statements)
            
            # Extraire les écritures du grand livre pour le compte 512200 spécifiquement
            ledger_entries = self._extract_bank_ledger_entries_improved(ledger_docs, account_filter="512200")
            
            # Effectuer les différents types de vérifications
            if self.alert_types.get('missing_transactions', True):
                alerts.extend(self._detect_missing_transactions_improved(bank_transactions, ledger_entries))
            
            if self.alert_types.get('duplicate_transactions', True):
                alerts.extend(self._detect_duplicate_transactions_improved(bank_transactions, ledger_entries))
            
            if self.alert_types.get('amount_discrepancies', True):
                alerts.extend(self._detect_amount_discrepancies_improved(bank_transactions, ledger_entries))
            
            if self.alert_types.get('date_discrepancies', True):
                alerts.extend(self._detect_date_discrepancies_improved(bank_transactions, ledger_entries))
            
            if self.alert_types.get('weekend_transactions', True):
                alerts.extend(self._detect_weekend_transactions_improved(bank_transactions, "relevé bancaire"))
                alerts.extend(self._detect_weekend_transactions_improved(ledger_entries, "grand livre"))
            
            if self.alert_types.get('large_transactions', True):
                alerts.extend(self._detect_large_transactions_improved(bank_transactions, ledger_entries))
            
        except Exception as e:
            logger.error(f"Erreur lors du rapprochement bancaire: {str(e)}")
            alerts.append(self._create_alert(
                'Erreur rapprochement bancaire',
                f'Erreur lors du rapprochement: {str(e)}',
                'high', 'error', None, 'HAUTE', 'Système'
            ))
        
        return alerts

    def _perform_facture_ledger_reconciliation(self, facture_docs, ledger_docs):
        """Effectue le rapprochement entre factures et grand livre"""
        alerts = []
        
        try:
            # Extraire les informations des factures
            factures_data = self._extract_factures_data_improved(facture_docs)
            
            # Extraire les écritures du grand livre
            ledger_entries = self._extract_all_ledger_entries(ledger_docs)
            
            # Chercher les correspondances pour chaque facture
            for facture in factures_data:
                correspondances = self._chercher_correspondance_grand_livre_improved(facture, ledger_entries)
                
                if not correspondances:
                    delay_days = self._calculate_delay_days(facture.get('date_facturation'))
                    priority = self._get_priority_by_delay(delay_days)
                    
                    alerts.append(self._create_alert(
                        f'Facture sans correspondance - {facture["numero_facture"]}',
                        f'Facture {facture["numero_facture"]} ({facture["total_ttc"]}€) non trouvée dans le grand livre. Client: {facture["client"]}',
                        priority, 'FACTURE_MANQUANTE_GRAND_LIVRE',
                        facture['document_id'], self._get_severity_by_priority(priority),
                        facture['fichier_source'], facture["total_ttc"]
                    ))
                else:
                    # Vérifier les écarts de montants dans les correspondances
                    for corr in correspondances:
                        if corr['type'] == 'montant_approx':
                            ecart = abs(float(facture['total_ttc']) - corr['montant_trouve'])
                            if ecart > self.config['amount_tolerance_absolute']:
                                alerts.append(self._create_alert(
                                    f'Écart de montant facture - {facture["numero_facture"]}',
                                    f'Écart de {ecart:.2f}€ entre facture ({facture["total_ttc"]}€) et grand livre ({corr["montant_trouve"]}€)',
                                    'medium', 'ECART_MONTANT_FACTURE',
                                    facture['document_id'], 'MOYENNE',
                                    facture['fichier_source'], ecart
                                ))
                                
        except Exception as e:
            logger.error(f"Erreur lors du rapprochement factures: {str(e)}")
            alerts.append(self._create_alert(
                'Erreur rapprochement factures',
                f'Erreur lors du rapprochement factures-grand livre: {str(e)}',
                'high', 'error', None, 'HAUTE', 'Système'
            ))
        
        return alerts

    def _perform_cheque_ledger_reconciliation(self, cheque_docs, ledger_docs):
        """Effectue le rapprochement entre chèques et grand livre"""
        alerts = []
        
        try:
            # Extraire les informations des chèques
            cheques_data = self._extract_cheques_data_improved(cheque_docs)
            
            # Extraire les écritures du grand livre
            ledger_entries = self._extract_all_ledger_entries(ledger_docs)
            
            # Chercher les correspondances pour chaque chèque
            for cheque in cheques_data:
                correspondances = self._chercher_correspondance_cheque_grand_livre(cheque, ledger_entries)
                
                if not correspondances:
                    delay_days = self._calculate_delay_days(cheque.get('date'))
                    priority = self._get_priority_by_delay(delay_days)
                    
                    alerts.append(self._create_alert(
                        f'Chèque sans correspondance - {cheque["numero_cheque"]}',
                        f'Chèque {cheque["numero_cheque"]} ({cheque["montant"]}€) non trouvé dans le grand livre. Bénéficiaire: {cheque["beneficiaire"]}',
                        priority, 'CHEQUE_MANQUANT_GRAND_LIVRE',
                        cheque['document_id'], self._get_severity_by_priority(priority),
                        cheque['fichier_source'], cheque["montant"]
                    ))
                                
        except Exception as e:
            logger.error(f"Erreur lors du rapprochement chèques: {str(e)}")
            alerts.append(self._create_alert(
                'Erreur rapprochement chèques',
                f'Erreur lors du rapprochement chèques-grand livre: {str(e)}',
                'high', 'error', None, 'HAUTE', 'Système'
            ))
        
        return alerts

    def _extract_bank_transactions_improved(self, bank_statements):
        """Extrait les transactions des relevés bancaires avec méthode améliorée"""
        transactions = []
        
        for doc in bank_statements:
            try:
                with open(doc['output_path'], 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                operations = data.get('operations', [])
                for op in operations:
                    if isinstance(op, dict):
                        # Nettoyage et normalisation améliorés
                        montant = self._normalize_amount_improved(op.get('montant'))
                        date_norm = self._normalize_date_improved(op.get('date'))
                        
                        if date_norm and montant is not None:
                            transaction = {
                                'id': self._generate_transaction_id(op),
                                'date': date_norm,
                                'amount': montant,
                                'description': self._clean_description(op.get('libelle', '')),
                                'reference': op.get('reference', ''),
                                'source_file': doc['name'],
                                'document_id': doc['id'],
                                'type': 'bank'
                            }
                            transactions.append(transaction)
                            
            except Exception as e:
                logger.error(f"Erreur extraction transactions bancaires {doc['name']}: {str(e)}")
        
        return transactions

    def _extract_bank_ledger_entries_improved(self, ledger_docs, account_filter=None):
        """Extrait les écritures bancaires du grand livre avec filtrage de compte"""
        entries = []
        
        for doc in ledger_docs:
            try:
                with open(doc['output_path'], 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                ecritures = data.get('ecritures', data.get('lignes', []))
                for ecriture in ecritures:
                    if isinstance(ecriture, dict):
                        compte = str(ecriture.get('numero_compte', ''))
                        
                        # Filtrer par compte si spécifié
                        if account_filter and not compte.startswith(account_filter):
                            continue
                        
                        # Filtrer les comptes bancaires (512xxx) si pas de filtre spécifique
                        if not account_filter and not compte.startswith('512'):
                            continue
                        
                        # Calculer le montant net avec méthode améliorée
                        debit = self._normalize_amount_improved(ecriture.get('debit', 0))
                        credit = self._normalize_amount_improved(ecriture.get('credit', 0))
                        amount = debit - credit if debit or credit else None
                        
                        date_norm = self._normalize_date_improved(ecriture.get('date'))
                        
                        if date_norm and amount is not None:
                            entry = {
                                'id': self._generate_transaction_id(ecriture),
                                'date': date_norm,
                                'amount': amount,
                                'description': self._clean_description(ecriture.get('libelle', '')),
                                'account': compte,
                                'source_file': doc['name'],
                                'document_id': doc['id'],
                                'type': 'ledger'
                            }
                            entries.append(entry)
                            
            except Exception as e:
                logger.error(f"Erreur extraction écritures grand livre {doc['name']}: {str(e)}")
        
        return entries

    def _extract_factures_data_improved(self, facture_docs):
        """Extrait les données des factures avec méthode améliorée"""
        factures = []
        
        for doc in facture_docs:
            try:
                with open(doc['output_path'], 'r', encoding='utf-8') as f:
                    facture_json = json.load(f)
                
                facture_info = self._extraire_info_facture_improved(facture_json)
                facture_info['document_id'] = doc['id']
                facture_info['fichier_source'] = doc['name']
                
                factures.append(facture_info)
                
            except Exception as e:
                logger.error(f"Erreur extraction facture {doc['name']}: {str(e)}")
        
        return factures

    def _extract_cheques_data_improved(self, cheque_docs):
        """Extrait les données des chèques avec méthode améliorée"""
        cheques = []
        
        for doc in cheque_docs:
            try:
                with open(doc['output_path'], 'r', encoding='utf-8') as f:
                    cheque_json = json.load(f)
                
                cheque_info = {
                    'numero_cheque': cheque_json.get('numero_cheque', ''),
                    'date': self._normalize_date_improved(cheque_json.get('date')),
                    'montant': self._normalize_amount_improved(cheque_json.get('montant')),
                    'beneficiaire': cheque_json.get('beneficiaire', ''),
                    'document_id': doc['id'],
                    'fichier_source': doc['name']
                }
                
                if cheque_info['montant'] is not None:
                    cheques.append(cheque_info)
                
            except Exception as e:
                logger.error(f"Erreur extraction chèque {doc['name']}: {str(e)}")
        
        return cheques

    def _extract_all_ledger_entries(self, ledger_docs):
        """Extrait toutes les écritures du grand livre"""
        entries = []
        
        for doc in ledger_docs:
            try:
                with open(doc['output_path'], 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                ecritures = data.get('ecritures', data.get('lignes', []))
                for ecriture in ecritures:
                    if isinstance(ecriture, dict):
                        debit = self._normalize_amount_improved(ecriture.get('debit', 0))
                        credit = self._normalize_amount_improved(ecriture.get('credit', 0))
                        
                        entry = {
                            'numero_compte': str(ecriture.get('numero_compte', '')),
                            'libelle': self._clean_description(ecriture.get('libelle', '')),
                            'date': self._normalize_date_improved(ecriture.get('date')),
                            'debit': debit or 0,
                            'credit': credit or 0,
                            'montant_net': (debit or 0) - (credit or 0),
                            'document_id': doc['id'],
                            'source_file': doc['name']
                        }
                        entries.append(entry)
                        
            except Exception as e:
                logger.error(f"Erreur extraction toutes écritures {doc['name']}: {str(e)}")
        
        return entries

    def _extraire_info_facture_improved(self, facture):
        """Extrait les informations clés d'une facture avec méthode améliorée"""
        info = {}

        # Extraction des informations de paiement
        if 'info payment' in facture:
            info_payment = facture['info payment']
            info['numero_facture'] = info_payment.get('Numéro Facture', '')
            info['date_facturation'] = self._normalize_date_improved(info_payment.get('Date Facturation', ''))
            info['total_ttc'] = self._normalize_amount_improved(info_payment.get('Total TTC', 0))
            info['client'] = info_payment.get('Nom du Client', '')

        info['nom_societe'] = facture.get('Nom Societe', '')

        # Calcul des totaux depuis la table si disponible
        if 'table' in facture:
            total_ht = 0
            total_tva = 0

            for item in facture['table']:
                try:
                    montant_ht = self._normalize_amount_improved(item.get('Montant HT', 0)) or 0
                    tva_rate = self._normalize_amount_improved(item.get('TVA', 0)) or 0

                    total_ht += montant_ht
                    total_tva += montant_ht * (tva_rate / 100)
                except (ValueError, TypeError) as e:
                    logger.warning(f"Erreur de conversion pour un item de facture: {e}")
                    continue

            info['total_ht_calcule'] = total_ht
            info['total_tva_calcule'] = total_tva

        return info

    def _chercher_correspondance_grand_livre_improved(self, facture_info, grand_livre_entries):
        """Cherche si une facture a une correspondance dans le grand livre avec méthode améliorée"""
        numero_facture = facture_info.get('numero_facture', '')
        total_ttc = facture_info.get('total_ttc', 0)
        
        correspondances = []
        tolerance = self.config.get('amount_tolerance_absolute', 0.10)

        # Recherche par numéro de facture dans le libellé
        if numero_facture:
            for entry in grand_livre_entries:
                if numero_facture.lower() in entry['libelle'].lower():
                    correspondances.append({
                        'type': 'numero_facture',
                        'entry': entry,
                        'montant_trouve': abs(entry['montant_net'])
                    })

        # Recherche par montant (débit ou crédit proche du total TTC)
        if total_ttc > 0:
            for entry in grand_livre_entries:
                montant_entry = abs(entry['montant_net'])
                if abs(montant_entry - total_ttc) <= tolerance:
                    correspondances.append({
                        'type': 'montant_exact',
                        'entry': entry,
                        'montant_trouve': montant_entry
                    })
                elif abs(montant_entry - total_ttc) <= total_ttc * (self.config.get('amount_tolerance_percentage', 2.0) / 100):
                    correspondances.append({
                        'type': 'montant_approx',
                        'entry': entry,
                        'montant_trouve': montant_entry
                    })

        return correspondances

    def _chercher_correspondance_cheque_grand_livre(self, cheque_info, grand_livre_entries):
        """Cherche si un chèque a une correspondance dans le grand livre"""
        numero_cheque = cheque_info.get('numero_cheque', '')
        montant = cheque_info.get('montant', 0)
        
        correspondances = []
        tolerance = self.config.get('amount_tolerance_absolute', 0.50)

        # Recherche par numéro de chèque dans le libellé
        if numero_cheque:
            for entry in grand_livre_entries:
                if numero_cheque.lower() in entry['libelle'].lower():
                    correspondances.append({
                        'type': 'numero_cheque',
                        'entry': entry,
                        'montant_trouve': abs(entry['montant_net'])
                    })

        # Recherche par montant
        if montant > 0:
            for entry in grand_livre_entries:
                montant_entry = abs(entry['montant_net'])
                if abs(montant_entry - montant) <= tolerance:
                    correspondances.append({
                        'type': 'montant_exact',
                        'entry': entry,
                        'montant_trouve': montant_entry
                    })

        return correspondances

    def _detect_weekend_transactions_improved(self, transactions, source_type):
        """Détecte les transactions effectuées le week-end avec liste détaillée"""
        alerts = []
        
        if not self.alert_types.get('weekend_transactions', True):
            return alerts
        
        try:
            weekend_transactions = []
            
            for tx in transactions:
                if tx.get('date'):
                    tx_date = datetime.strptime(tx['date'], '%Y-%m-%d')
                    if tx_date.weekday() >= 5:  # Samedi (5) ou Dimanche (6)
                        weekend_transactions.append(tx)
            
            if weekend_transactions:
                # Grouper par fichier source
                transactions_par_fichier = defaultdict(list)
                for tx in weekend_transactions:
                    transactions_par_fichier[tx['source_file']].append(tx)
                
                # Créer une alerte détaillée pour chaque fichier
                for fichier, txs in transactions_par_fichier.items():
                    total_amount = sum(abs(tx['amount']) for tx in txs)
                    
                    # Créer la description détaillée
                    details = []
                    for tx in txs[:5]:  # Limiter à 5 transactions pour la lisibilité
                        day_name = datetime.strptime(tx['date'], '%Y-%m-%d').strftime('%A')
                        details.append(f"• {tx['date']} ({day_name}): {tx['amount']:.2f}€ - {tx['description'][:50]}")
                    
                    if len(txs) > 5:
                        details.append(f"... et {len(txs) - 5} autres transactions")
                    
                    description = f"Transactions {source_type} effectuées le week-end dans {fichier}:\n" + "\n".join(details)
                    
                    alerts.append(self._create_alert(
                        f'Transactions week-end - {source_type}',
                        description,
                        'low', 'TRANSACTIONS_WEEKEND',
                        txs[0]['document_id'], 'FAIBLE',
                        fichier, total_amount
                    ))
                    
        except Exception as e:
            logger.error(f"Erreur détection transactions week-end: {str(e)}")
        
        return alerts

    def _detect_missing_transactions_improved(self, bank_transactions, ledger_entries):
        """Détecte les transactions manquantes avec méthode améliorée"""
        alerts = []
        
        if not self.alert_types.get('missing_transactions', True):
            return alerts
        
        try:
            # Transactions bancaires non trouvées dans le grand livre
            for bank_tx in bank_transactions:
                matched = self._find_matching_transaction_improved(bank_tx, ledger_entries)
                if not matched:
                    delay_days = self._calculate_delay_days(bank_tx['date'])
                    priority = self._get_priority_by_delay(delay_days)
                    
                    alerts.append(self._create_alert(
                        f'Transaction manquante dans grand livre (512200)',
                        f'Transaction bancaire du {bank_tx["date"]} ({bank_tx["amount"]:.2f}€) non trouvée dans le grand livre. Délai: {delay_days} jours. Description: {bank_tx["description"][:100]}',
                        priority, 'TRANSACTION_MANQUANTE_GRAND_LIVRE', 
                        bank_tx['document_id'], self._get_severity_by_priority(priority),
                        bank_tx['source_file'], bank_tx["amount"]
                    ))
            
            # Écritures du grand livre non trouvées dans les relevés
            for ledger_entry in ledger_entries:
                matched = self._find_matching_transaction_improved(ledger_entry, bank_transactions)
                if not matched:
                    delay_days = self._calculate_delay_days(ledger_entry['date'])
                    priority = self._get_priority_by_delay(delay_days)
                    
                    alerts.append(self._create_alert(
                        f'Écriture manquante dans relevé bancaire (512200)',
                        f'Écriture comptable du {ledger_entry["date"]} ({ledger_entry["amount"]:.2f}€) non trouvée dans les relevés bancaires. Délai: {delay_days} jours. Description: {ledger_entry["description"][:100]}',
                        priority, 'TRANSACTION_MANQUANTE_RELEVE',
                        ledger_entry['document_id'], self._get_severity_by_priority(priority),
                        ledger_entry['source_file'], ledger_entry["amount"]
                    ))
                    
        except Exception as e:
            logger.error(f"Erreur détection transactions manquantes: {str(e)}")
        
        return alerts

    def _detect_duplicate_transactions_improved(self, bank_transactions, ledger_entries):
        """Détecte les transactions dupliquées avec méthode améliorée"""
        alerts = []
        
        if not self.alert_types.get('duplicate_transactions', True):
            return alerts
        
        try:
            # Détecter les doublons dans les relevés bancaires
            bank_duplicates = self._find_duplicates_improved(bank_transactions)
            for dup_group in bank_duplicates:
                if len(dup_group) > 1:
                    amounts = [tx['amount'] for tx in dup_group]
                    files = list(set([tx['source_file'] for tx in dup_group]))
                    descriptions = [tx['description'][:50] for tx in dup_group[:3]]
                    
                    description = f'{len(dup_group)} transactions bancaires identiques détectées: {amounts[0]:.2f}€ le {dup_group[0]["date"]}. Descriptions: {", ".join(descriptions)}'
                    
                    alerts.append(self._create_alert(
                        'Transactions bancaires dupliquées',
                        description,
                        'medium', 'DOUBLON_RELEVE_BANCAIRE',
                        dup_group[0]['document_id'], 'MOYENNE',
                        ', '.join(files), amounts[0]
                    ))
            
            # Détecter les doublons dans le grand livre
            ledger_duplicates = self._find_duplicates_improved(ledger_entries)
            for dup_group in ledger_duplicates:
                if len(dup_group) > 1:
                    amounts = [entry['amount'] for entry in dup_group]
                    files = list(set([entry['source_file'] for entry in dup_group]))
                    descriptions = [entry['description'][:50] for entry in dup_group[:3]]
                    
                    description = f'{len(dup_group)} écritures comptables identiques détectées: {amounts[0]:.2f}€ le {dup_group[0]["date"]}. Descriptions: {", ".join(descriptions)}'
                    
                    alerts.append(self._create_alert(
                        'Écritures comptables dupliquées',
                        description,
                        'medium', 'DOUBLON_GRAND_LIVRE',
                        dup_group[0]['document_id'], 'MOYENNE',
                        ', '.join(files), amounts[0]
                    ))
                    
        except Exception as e:
            logger.error(f"Erreur détection doublons: {str(e)}")
        
        return alerts

    def _detect_amount_discrepancies_improved(self, bank_transactions, ledger_entries):
        """Détecte les écarts de montants avec méthode améliorée"""
        alerts = []
        
        if not self.alert_types.get('amount_discrepancies', True):
            return alerts
        
        try:
            tolerance_abs = self.config.get('amount_tolerance_absolute', 0.50)
            tolerance_pct = self.config.get('amount_tolerance_percentage', 2.0)
            
            for bank_tx in bank_transactions:
                for ledger_entry in ledger_entries:
                    if self._dates_are_close_improved(bank_tx['date'], ledger_entry['date'], 3):
                        amount_diff = abs(bank_tx['amount'] - ledger_entry['amount'])
                        
                        # Vérifier si l'écart dépasse les tolérances
                        if amount_diff > tolerance_abs:
                            percent_diff = (amount_diff / abs(bank_tx['amount'])) * 100 if bank_tx['amount'] != 0 else 0
                            
                            if percent_diff > tolerance_pct:
                                priority = 'high' if amount_diff > 1000 else 'medium'
                                
                                description = f'Écart de {amount_diff:.2f}€ ({percent_diff:.1f}%) entre relevé ({bank_tx["amount"]:.2f}€) et grand livre ({ledger_entry["amount"]:.2f}€) pour le {bank_tx["date"]}. Relevé: "{bank_tx["description"][:50]}" vs Grand livre: "{ledger_entry["description"][:50]}"'
                                
                                alerts.append(self._create_alert(
                                    'Écart de montant détecté (512200)',
                                    description,
                                    priority, 'ECART_MONTANT',
                                    bank_tx['document_id'], self._get_severity_by_priority(priority),
                                    f'{bank_tx["source_file"]} vs {ledger_entry["source_file"]}',
                                    amount_diff
                                ))
                                
        except Exception as e:
            logger.error(f"Erreur détection écarts montants: {str(e)}")
        
        return alerts

    def _detect_date_discrepancies_improved(self, bank_transactions, ledger_entries):
        """Détecte les écarts de dates avec méthode améliorée"""
        alerts = []
        
        if not self.alert_types.get('date_discrepancies', True):
            return alerts
        
        try:
            tolerance_abs = self.config.get('amount_tolerance_absolute', 0.50)
            max_delay = self.config.get('max_date_delay_days', 3)
            
            for bank_tx in bank_transactions:
                matching_amounts = [entry for entry in ledger_entries 
                                  if abs(entry['amount'] - bank_tx['amount']) <= tolerance_abs]
                
                for ledger_entry in matching_amounts:
                    date_diff = self._calculate_date_difference_improved(bank_tx['date'], ledger_entry['date'])
                    
                    if date_diff > max_delay:
                        priority = self._get_priority_by_delay(date_diff)
                        
                        description = f'Écart de {date_diff} jours entre relevé ({bank_tx["date"]}) et grand livre ({ledger_entry["date"]}) pour {bank_tx["amount"]:.2f}€. Relevé: "{bank_tx["description"][:50]}" vs Grand livre: "{ledger_entry["description"][:50]}"'
                        
                        alerts.append(self._create_alert(
                            'Écart de date important (512200)',
                            description,
                            priority, 'ECART_DATE',
                            bank_tx['document_id'], self._get_severity_by_priority(priority),
                            f'{bank_tx["source_file"]} vs {ledger_entry["source_file"]}',
                            bank_tx["amount"]
                        ))
                        
        except Exception as e:
            logger.error(f"Erreur détection écarts dates: {str(e)}")
        
        return alerts

    def _detect_large_transactions_improved(self, bank_transactions, ledger_entries):
        """Détecte les grosses transactions avec méthode améliorée"""
        alerts = []
        
        if not self.alert_types.get('large_transactions', True):
            return alerts
        
        try:
            threshold = self.config.get('large_transaction_threshold', 5000)
            critical_threshold = self.config.get('critical_amount_threshold', 50000)
            
            # Transactions bancaires importantes
            for tx in bank_transactions:
                if abs(tx['amount']) > threshold:
                    priority = 'high' if abs(tx['amount']) > critical_threshold else 'medium'
                    
                    description = f'Transaction bancaire importante de {tx["amount"]:.2f}€ détectée le {tx["date"]} - Vérification recommandée. Description: "{tx["description"][:100]}"'
                    
                    alerts.append(self._create_alert(
                        'Transaction bancaire importante',
                        description,
                        priority, 'GROSSE_TRANSACTION_BANCAIRE',
                        tx['document_id'], self._get_severity_by_priority(priority),
                        tx['source_file'], abs(tx["amount"])
                    ))
            
            # Écritures comptables importantes
            for entry in ledger_entries:
                if abs(entry['amount']) > threshold:
                    priority = 'high' if abs(entry['amount']) > critical_threshold else 'medium'
                    
                    description = f'Écriture comptable importante de {entry["amount"]:.2f}€ détectée le {entry["date"]} - Vérification recommandée. Description: "{entry["description"][:100]}"'
                    
                    alerts.append(self._create_alert(
                        'Écriture comptable importante',
                        description,
                        priority, 'GROSSE_TRANSACTION_COMPTABLE',
                        entry['document_id'], self._get_severity_by_priority(priority),
                        entry['source_file'], abs(entry["amount"])
                    ))
                    
        except Exception as e:
            logger.error(f"Erreur détection grosses transactions: {str(e)}")
        
        return alerts

    # Méthodes utilitaires améliorées
    def _normalize_amount_improved(self, amount_str):
        """Normalise les montants avec méthode améliorée"""
        if not amount_str or amount_str == 'N/A':
            return None
        
        try:
            # Convertir en string et nettoyer
            amount_str = str(amount_str).strip()
            
            # Supprimer les caractères non numériques sauf . , - et espaces
            import re
            amount_str = re.sub(r'[^\d\.,\-\s]', '', amount_str)
            
            # Remplacer les virgules par des points et supprimer les espaces
            amount_str = amount_str.replace(',', '.').replace(' ', '')
            
            # Gérer les cas de multiples points
            if amount_str.count('.') > 1:
                # Garder seulement le dernier point comme séparateur décimal
                parts = amount_str.split('.')
                amount_str = ''.join(parts[:-1]) + '.' + parts[-1]
            
            return float(amount_str) if amount_str else None
        except (ValueError, TypeError):
            return None

    def _normalize_date_improved(self, date_str):
        """Normalise les dates avec méthode améliorée"""
        if not date_str or date_str == 'N/A':
            return None
        
        # Formats de date supportés
        date_formats = [
            '%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y', '%d/%m/%y', '%Y/%m/%d',
            '%d.%m.%Y', '%Y.%m.%d', '%d %m %Y', '%Y %m %d'
        ]
        
        date_str = str(date_str).strip()
        
        for fmt in date_formats:
            try:
                date_obj = datetime.strptime(date_str, fmt)
                return date_obj.strftime('%Y-%m-%d')
            except ValueError:
                continue
        
        return None

    def _clean_description(self, description):
        """Nettoie et normalise les descriptions"""
        if not description:
            return ''
        
        # Nettoyer les caractères spéciaux et normaliser les espaces
        import re
        description = re.sub(r'\s+', ' ', str(description).strip())
        return description

    def _find_matching_transaction_improved(self, transaction, transaction_list):
        """Trouve une transaction correspondante avec méthode améliorée"""
        tolerance_abs = self.config.get('amount_tolerance_absolute', 0.50)
        tolerance_pct = self.config.get('amount_tolerance_percentage', 2.0)
        
        for other_tx in transaction_list:
            # Vérifier la proximité des dates
            if self._dates_are_close_improved(transaction['date'], other_tx['date'], 3):
                # Vérifier la proximité des montants
                amount_diff = abs(transaction['amount'] - other_tx['amount'])
                if amount_diff <= tolerance_abs:
                    return other_tx
                
                # Vérifier le pourcentage de différence
                if transaction['amount'] != 0:
                    percent_diff = (amount_diff / abs(transaction['amount'])) * 100
                    if percent_diff <= tolerance_pct:
                        return other_tx
        
        return None

    def _find_duplicates_improved(self, transactions):
        """Trouve les transactions dupliquées avec méthode améliorée"""
        groups = defaultdict(list)
        
        for tx in transactions:
            # Créer une clé basée sur la date, le montant arrondi et une partie de la description
            description_key = tx['description'][:20].lower() if tx['description'] else ''
            key = f"{tx['date']}_{tx['amount']:.2f}_{description_key}"
            groups[key].append(tx)
        
        return [group for group in groups.values() if len(group) > 1]

    def _dates_are_close_improved(self, date1, date2, max_days=3):
        """Vérifie si deux dates sont proches avec méthode améliorée"""
        if not date1 or not date2:
            return False
        
        try:
            d1 = datetime.strptime(date1, '%Y-%m-%d')
            d2 = datetime.strptime(date2, '%Y-%m-%d')
            return abs((d1 - d2).days) <= max_days
        except ValueError:
            return False

    def _calculate_date_difference_improved(self, date1, date2):
        """Calcule la différence en jours entre deux dates avec méthode améliorée"""
        try:
            d1 = datetime.strptime(date1, '%Y-%m-%d')
            d2 = datetime.strptime(date2, '%Y-%m-%d')
            return abs((d1 - d2).days)
        except ValueError:
            return 0

    # Méthodes existantes conservées
    def _create_alert(self, title, description, priority, alert_type, document_id, severity, source_file, amount=None):
        """Crée une alerte standardisée"""
        return {
            'id': len(self.alerts) + 1,
            'title': title,
            'description': description,
            'priority': priority,
            'type': alert_type,
            'date': datetime.now().strftime('%Y-%m-%d'),
            'status': 'active',
            'document_id': document_id,
            'severite': severity,
            'source_file': source_file,
            'montant': amount
        }

    def _generate_transaction_id(self, transaction_data):
        """Génère un ID unique pour une transaction basé sur ses données"""
        data_str = f"{transaction_data.get('date', '')}{transaction_data.get('montant', '')}{transaction_data.get('libelle', '')}"
        return hashlib.md5(data_str.encode()).hexdigest()[:12]

    def _calculate_delay_days(self, transaction_date):
        """Calcule le délai en jours depuis la transaction"""
        if not transaction_date:
            return 0
        
        try:
            tx_date = datetime.strptime(transaction_date, '%Y-%m-%d')
            return (datetime.now() - tx_date).days
        except ValueError:
            return 0

    def _get_priority_by_delay(self, delay_days):
        """Détermine la priorité basée sur le délai"""
        if delay_days <= self.config.get('high_priority_delay_days', 1):
            return 'high'
        elif delay_days <= self.config.get('medium_priority_delay_days', 7):
            return 'medium'
        else:
            return 'low'

    def _get_severity_by_priority(self, priority):
        """Convertit la priorité en sévérité"""
        severity_map = {'high': 'HAUTE', 'medium': 'MOYENNE', 'low': 'FAIBLE'}
        return severity_map.get(priority, 'FAIBLE')

    def _has_meaningful_data(self, json_data, required_fields):
        """Vérifie si le document a suffisamment de données valides"""
        valid_fields = 0
        for field in required_fields:
            if field in json_data and json_data[field] and json_data[field] != 'N/A':
                valid_fields += 1
        return valid_fields >= len(required_fields) / 2

    def _analyze_facture_json(self, doc, json_data):
        """Analyse le JSON d'une facture pour détecter des anomalies"""
        alerts = []
        
        try:
            required_fields = ['montant', 'date', 'numero_facture', 'fournisseur']
            missing_fields = []
            
            if self._has_meaningful_data(json_data, required_fields):
                for field in required_fields:
                    if field not in json_data or not json_data[field] or json_data[field] == 'N/A':
                        missing_fields.append(field)
                
                if len(missing_fields) > 2:
                    alerts.append(self._create_alert(
                        f'Données incomplètes - Facture {doc["name"]}',
                        f'Champs manquants: {", ".join(missing_fields)}',
                        'low', 'INCOHERENCE_MONTANT_FACTURE',
                        doc['id'], 'FAIBLE', doc["name"],
                        json_data.get('montant', 'N/A')
                    ))
            
            # Vérifier les montants suspects
            if 'montant' in json_data and json_data['montant'] and json_data['montant'] != 'N/A':
                try:
                    montant = self._normalize_amount_improved(json_data['montant'])
                    if montant:
                        critical_threshold = self.config['critical_amount_threshold']
                        suspicious_threshold = self.config['suspicious_amount_threshold']
                        
                        if montant > critical_threshold:
                            alerts.append(self._create_alert(
                                f'Montant élevé détecté - {doc["name"]}',
                                f'Montant de {montant}€ nécessite une validation',
                                'high', 'ARRONDI_SUSPECT',
                                doc['id'], 'HAUTE', doc["name"], montant
                            ))
                        
                        if montant > suspicious_threshold and montant % 1000 == 0:
                            alerts.append(self._create_alert(
                                f'Montant rond suspect - {doc["name"]}',
                                f'Montant de {montant}€ (montant rond) à vérifier',
                                'low', 'ARRONDI_SUSPECT',
                                doc['id'], 'FAIBLE', doc["name"], montant
                            ))
                            
                except ValueError:
                    if len(str(json_data['montant'])) > 3:
                        alerts.append(self._create_alert(
                            f'Format montant invalide - {doc["name"]}',
                            f'Le montant "{json_data["montant"]}" n\'est pas dans un format valide',
                            'low', 'error',
                            doc['id'], 'FAIBLE', doc["name"]
                        ))
            
            # Vérifier les dates
            if 'date' in json_data and json_data['date'] and json_data['date'] != 'N/A':
                normalized_date = self._normalize_date_improved(json_data['date'])
                if normalized_date:
                    date_obj = datetime.strptime(normalized_date, '%Y-%m-%d')
                    
                    if date_obj > datetime.now():
                        alerts.append(self._create_alert(
                            f'Date future détectée - {doc["name"]}',
                            f'Date de facture dans le futur: {json_data["date"]}',
                            'medium', 'SEQUENCE_ILLOGIQUE',
                            doc['id'], 'MOYENNE', doc["name"]
                        ))
                    
                    if date_obj < datetime.now() - timedelta(days=1825):
                        alerts.append(self._create_alert(
                            f'Facture très ancienne - {doc["name"]}',
                            f'Facture datée de plus de 5 ans: {json_data["date"]}',
                            'low', 'info',
                            doc['id'], 'FAIBLE', doc["name"]
                        ))
                else:
                    if len(str(json_data['date'])) > 5:
                        alerts.append(self._create_alert(
                            f'Format date invalide - {doc["name"]}',
                            f'Format de date non reconnu: {json_data["date"]}',
                            'low', 'error',
                            doc['id'], 'FAIBLE', doc["name"]
                        ))
                    
        except Exception as e:
            alerts.append(self._create_alert(
                f'Erreur analyse facture - {doc["name"]}',
                f'Erreur lors de l\'analyse: {str(e)}',
                'medium', 'error',
                doc['id'], 'MOYENNE', doc["name"]
            ))
        
        return alerts

    def _analyze_cheque_json(self, doc, json_data):
        """Analyse le JSON d'un chèque pour détecter des anomalies"""
        alerts = []
        
        try:
            required_fields = ['montant', 'date', 'numero_cheque', 'beneficiaire']
            missing_fields = []
            
            if self._has_meaningful_data(json_data, required_fields):
                for field in required_fields:
                    if field not in json_data or not json_data[field] or json_data[field] == 'N/A':
                        missing_fields.append(field)
                
                if len(missing_fields) > 2:
                    alerts.append(self._create_alert(
                        f'Informations chèque incomplètes - {doc["name"]}',
                        f'Champs manquants: {", ".join(missing_fields)}',
                        'medium', 'INFORMATIONS_BANCAIRES_INCOMPLETES',
                        doc['id'], 'MOYENNE', doc["name"]
                    ))
            
            if ('montant' in json_data and json_data['montant'] and json_data['montant'] != 'N/A' and
                'montant_lettres' in json_data and json_data['montant_lettres'] and json_data['montant_lettres'] != 'N/A'):
                
                alerts.append(self._create_alert(
                    f'Vérification montant chèque - {doc["name"]}',
                    f'Vérifier cohérence: {json_data["montant"]} vs {json_data["montant_lettres"]}',
                    'low', 'ECART_MONTANT',
                    doc['id'], 'FAIBLE', doc["name"],
                    json_data['montant']
                ))
                    
        except Exception as e:
            alerts.append(self._create_alert(
                f'Erreur analyse chèque - {doc["name"]}',
                f'Erreur lors de l\'analyse: {str(e)}',
                'medium', 'error',
                doc['id'], 'MOYENNE', doc["name"]
            ))
        
        return alerts

    def _analyze_releve_json(self, doc, json_data):
        """Analyse le JSON d'un relevé bancaire"""
        alerts = []
        
        try:
            if 'operations' in json_data:
                operations = json_data['operations']
                if isinstance(operations, list) and len(operations) > 0:
                    
                    high_amount_count = 0
                    for operation in operations:
                        if isinstance(operation, dict):
                            if 'montant' in operation and operation['montant']:
                                try:
                                    montant = self._normalize_amount_improved(operation['montant'])
                                    if montant and abs(montant) > self.config['critical_amount_threshold']:
                                        high_amount_count += 1
                                        if high_amount_count <= 3:
                                            alerts.append(self._create_alert(
                                                f'Opération bancaire importante - {doc["name"]}',
                                                f'Opération de {montant:.2f}€ nécessite une vérification',
                                                'high', 'ECART_MONTANT',
                                                doc['id'], 'HAUTE', doc["name"], montant
                                            ))
                                except ValueError:
                                    pass
                    
                    if len(operations) > 200:
                        alerts.append(self._create_alert(
                            f'Volume élevé d\'opérations - {doc["name"]}',
                            f'{len(operations)} opérations détectées, vérification recommandée',
                            'low', 'info',
                            doc['id'], 'FAIBLE', doc["name"]
                        ))
                else:
                    alerts.append(self._create_alert(
                        f'Relevé vide - {doc["name"]}',
                        'Aucune opération détectée dans le relevé',
                        'low', 'OPERATION_MANQUANTE_GRAND_LIVRE',
                        doc['id'], 'FAIBLE', doc["name"]
                    ))
                    
        except Exception as e:
            alerts.append(self._create_alert(
                f'Erreur analyse relevé - {doc["name"]}',
                f'Erreur lors de l\'analyse: {str(e)}',
                'medium', 'error',
                doc['id'], 'MOYENNE', doc["name"]
            ))
        
        return alerts

    def _analyze_grandlivre_json(self, doc, json_data):
        """Analyse le JSON d'un grand livre"""
        alerts = []
        
        try:
            if 'ecritures' in json_data or 'lignes' in json_data:
                ecritures = json_data.get('ecritures', json_data.get('lignes', []))
                
                if isinstance(ecritures, list) and len(ecritures) > 0:
                    
                    debit_total = 0
                    credit_total = 0
                    
                    for ecriture in ecritures:
                        if isinstance(ecriture, dict):
                            debit = self._normalize_amount_improved(ecriture.get('debit', 0)) or 0
                            credit = self._normalize_amount_improved(ecriture.get('credit', 0)) or 0
                            debit_total += debit
                            credit_total += credit
                    
                    difference = abs(debit_total - credit_total)
                    tolerance = self.config['amount_tolerance_absolute']
                    
                    if difference > tolerance:
                        alerts.append(self._create_alert(
                            f'Déséquilibre comptable - {doc["name"]}',
                            f'Écart débit/crédit: {difference:.2f}€ (Débit: {debit_total:.2f}€, Crédit: {credit_total:.2f}€)',
                            'high', 'DOUBLON_GRAND_LIVRE',
                            doc['id'], 'HAUTE', doc["name"], difference
                        ))
                    
                    if len(ecritures) > 2000:
                        alerts.append(self._create_alert(
                            f'Volume important d\'écritures - {doc["name"]}',
                            f'{len(ecritures)} écritures détectées, contrôle approfondi recommandé',
                            'low', 'info',
                            doc['id'], 'FAIBLE', doc["name"]
                        ))
                        
                else:
                    alerts.append(self._create_alert(
                        f'Grand livre vide - {doc["name"]}',
                        'Aucune écriture détectée dans le grand livre',
                        'low', 'OPERATION_MANQUANTE_GRAND_LIVRE',
                        doc['id'], 'FAIBLE', doc["name"]
                    ))
                    
        except Exception as e:
            alerts.append(self._create_alert(
                f'Erreur analyse grand livre - {doc["name"]}',
                f'Erreur lors de l\'analyse: {str(e)}',
                'medium', 'error',
                doc['id'], 'MOYENNE', doc["name"]
            ))
        
        return alerts

    def _generate_closure_alerts(self):
        """Génère des alertes de clôture basées sur la date actuelle"""
        alerts = []
        now = datetime.now()
        
        if now.day > 28:
            alerts.append(self._create_alert(
                'Clôture mensuelle approche',
                'La clôture mensuelle approche. Vérifiez que tous les documents sont traités.',
                'medium', 'warning',
                None, 'MOYENNE', 'Système'
            ))
        
        if now.month == 12 and now.day > 20:
            alerts.append(self._create_alert(
                'Clôture annuelle - Préparation',
                'Préparation de la clôture annuelle. Vérification des écritures de régularisation nécessaire.',
                'high', 'warning',
                None, 'HAUTE', 'Système'
            ))
        
        return alerts

    def calculate_risk_score(self, alerts, total_documents):
        """Calcule un score de risque basé sur les alertes et la configuration"""
        if not alerts or total_documents == 0:
            return {'score': 0, 'niveau': 'FAIBLE'}
        
        severity_weights = {'HAUTE': 8, 'MOYENNE': 3, 'FAIBLE': 1}
        type_weights = {
            'DOUBLON_GRAND_LIVRE': 6,
            'ARRONDI_SUSPECT': 5,
            'ECART_MONTANT': 4,
            'INCOHERENCE_MONTANT_FACTURE': 3,
            'SEQUENCE_ILLOGIQUE': 3,
            'INFORMATIONS_BANCAIRES_INCOMPLETES': 3,
            'OPERATION_MANQUANTE_GRAND_LIVRE': 2,
            'TRANSACTION_MANQUANTE_GRAND_LIVRE': 6,
            'TRANSACTION_MANQUANTE_RELEVE': 6,
            'DOUBLON_RELEVE_BANCAIRE': 5,
            'ECART_DATE': 4,
            'TRANSACTIONS_NON_RAPPROCHEES': 7,
            'TRANSACTIONS_WEEKEND': 1,
            'GROSSE_TRANSACTION_BANCAIRE': 3,
            'GROSSE_TRANSACTION_COMPTABLE': 3,
            'FACTURE_MANQUANTE_GRAND_LIVRE': 5,
            'CHEQUE_MANQUANT_GRAND_LIVRE': 5,
            'ECART_MONTANT_FACTURE': 4,
            'error': 2,
            'warning': 1,
            'info': 0.5
        }
        
        weighted_score = 0
        for alert in alerts:
            severity = alert.get('severite', 'FAIBLE')
            alert_type = alert.get('type', 'info')
            
            severity_weight = severity_weights.get(severity, 1)
            type_weight = type_weights.get(alert_type, 1)
            
            weighted_score += severity_weight * type_weight
        
        normalized_score = weighted_score / max(total_documents, 1)
        final_score = min(100, int(20 * math.log(normalized_score + 1)))
        
        if final_score >= self.config['critical_threshold']:
            niveau = 'CRITIQUE'
        elif final_score >= self.config['high_threshold']:
            niveau = 'ÉLEVÉ'
        elif final_score >= self.config['medium_threshold']:
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
            'alertes_par_severite': {},
            'alertes_par_type': {},
            'fichiers_concernes': {}
        }
        
        statuts = [alerte.get('status', 'active') for alerte in alertes]
        rapport['repartition_statuts'] = dict(Counter(statuts))
        
        severites = [alerte.get('severite', 'FAIBLE') for alerte in alertes]
        rapport['alertes_par_severite'] = dict(Counter(severites))
        
        types = [alerte.get('type', 'info') for alerte in alertes]
        rapport['alertes_par_type'] = dict(Counter(types))
        
        fichiers = [alerte.get('source_file', 'Inconnu') for alerte in alertes if alerte.get('source_file')]
        rapport['fichiers_concernes'] = dict(Counter(fichiers))
        
        return rapport


def extract_grandlivre_data(documents_db):
    """Extrait et analyse les données du grand livre pour le dashboard"""
    try:
        grandlivre_docs = [d for d in documents_db if d['type'] == 'grandlivre' and d['status'] == 'completed']
        
        if not grandlivre_docs:
            return _get_empty_grandlivre_data()
        
        total_debit = 0
        total_credit = 0
        comptes = {}
        comptes_details = {
            'banque': [],
            'clients': [],
            'fournisseurs': [],
            'tva': []
        }
        
        for doc in grandlivre_docs:
            try:
                if os.path.exists(doc['output_path']):
                    with open(doc['output_path'], 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    ecritures = data.get('ecritures', data.get('lignes', []))
                    
                    for ecriture in ecritures:
                        if isinstance(ecriture, dict):
                            numero_compte = str(ecriture.get('numero_compte', ''))
                            libelle = ecriture.get('libelle', '')
                            
                            # Normaliser les montants
                            workflow = AnomalyDetectionWorkflow()
                            debit = workflow._normalize_amount_improved(ecriture.get('debit', 0)) or 0
                            credit = workflow._normalize_amount_improved(ecriture.get('credit', 0)) or 0
                            
                            total_debit += debit
                            total_credit += credit
                            
                            # Grouper par compte
                            if numero_compte not in comptes:
                                comptes[numero_compte] = {
                                    'libelle': libelle,
                                    'debit': 0,
                                    'credit': 0,
                                    'solde': 0
                                }
                            
                            comptes[numero_compte]['debit'] += debit
                            comptes[numero_compte]['credit'] += credit
                            comptes[numero_compte]['solde'] = comptes[numero_compte]['debit'] - comptes[numero_compte]['credit']
                            
                            # Classer par type de compte
                            if numero_compte.startswith('512'):  # Comptes bancaires
                                _add_to_compte_details(comptes_details['banque'], numero_compte, libelle, comptes[numero_compte]['solde'])
                            elif numero_compte.startswith('411'):  # Comptes clients
                                _add_to_compte_details(comptes_details['clients'], numero_compte, libelle, comptes[numero_compte]['solde'])
                            elif numero_compte.startswith('401'):  # Comptes fournisseurs
                                _add_to_compte_details(comptes_details['fournisseurs'], numero_compte, libelle, comptes[numero_compte]['solde'])
                            elif numero_compte.startswith('445'):  # Comptes TVA
                                _add_to_compte_details(comptes_details['tva'], numero_compte, libelle, comptes[numero_compte]['solde'])
                                
            except Exception as e:
                logger.error(f"Erreur traitement grand livre {doc['name']}: {str(e)}")
                continue
        
        # Calculer les agrégats
        tva_deductible = sum(compte['solde'] for compte in comptes_details['tva'] if compte['solde'] > 0)
        tva_collectee = abs(sum(compte['solde'] for compte in comptes_details['tva'] if compte['solde'] < 0))
        solde_banque = sum(compte['solde'] for compte in comptes_details['banque'])
        creances_clients = sum(compte['solde'] for compte in comptes_details['clients'] if compte['solde'] > 0)
        dettes_fournisseurs = abs(sum(compte['solde'] for compte in comptes_details['fournisseurs'] if compte['solde'] < 0))
        
        return {
            'total_ecritures': len([e for doc in grandlivre_docs for e in _get_ecritures_from_doc(doc)]),
            'total_debit': total_debit,
            'total_credit': total_credit,
            'comptes': comptes,
            'tva_deductible': tva_deductible,
            'tva_collectee': tva_collectee,
            'balance': total_debit - total_credit,
            'solde_banque': solde_banque,
            'creances_clients': creances_clients,
            'dettes_fournisseurs': dettes_fournisseurs,
            'chiffre_affaires': 0,  # À calculer selon les comptes de vente
            'charges': 0,  # À calculer selon les comptes de charge
            'encaissements': 0,  # À calculer selon les mouvements bancaires
            'comptes_details': comptes_details
        }
        
    except Exception as e:
        logger.error(f"Erreur extraction données grand livre: {str(e)}")
        return _get_empty_grandlivre_data()


def _get_empty_grandlivre_data():
    """Retourne une structure vide pour les données du grand livre"""
    return {
        'total_ecritures': 0,
        'total_debit': 0,
        'total_credit': 0,
        'comptes': {},
        'tva_deductible': 0,
        'tva_collectee': 0,
        'balance': 0,
        'solde_banque': 0,
        'creances_clients': 0,
        'dettes_fournisseurs': 0,
        'chiffre_affaires': 0,
        'charges': 0,
        'encaissements': 0,
        'comptes_details': {
            'banque': [],
            'clients': [],
            'fournisseurs': [],
            'tva': []
        }
    }


def _add_to_compte_details(details_list, numero, libelle, solde):
    """Ajoute un compte aux détails s'il n'existe pas déjà"""
    existing = next((item for item in details_list if item['numero'] == numero), None)
    if existing:
        existing['solde'] = solde
    else:
        details_list.append({
            'numero': numero,
            'libelle': libelle,
            'solde': solde
        })


def _get_ecritures_from_doc(doc):
    """Récupère les écritures d'un document"""
    try:
        if os.path.exists(doc['output_path']):
            with open(doc['output_path'], 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data.get('ecritures', data.get('lignes', []))
    except:
        return []
    return []


def clean_numeric_column(series):
    """Nettoie une colonne numérique"""
    try:
        cleaned = series.astype(str).str.replace(',', '.').str.replace('€', '').str.replace(' ', '').str.strip()
        cleaned = cleaned.replace('', '0').replace('nan', '0')
        return pd.to_numeric(cleaned, errors='coerce').fillna(0.0)
    except Exception as e:
        logger.error(f"Erreur lors du nettoyage de la colonne numérique: {str(e)}")
        return pd.Series([0.0] * len(series))


def clean_grandlivre_dataframe(df):
    """Nettoie et standardise le DataFrame du grand livre"""
    try:
        column_mapping = {
            'n° compte': 'numero_compte', 'numero_compte': 'numero_compte', 'compte': 'numero_compte',
            'libellé': 'libelle', 'libelle': 'libelle', 'description': 'libelle',
            'débit': 'debit', 'debit': 'debit',
            'crédit': 'credit', 'credit': 'credit',
            'date': 'date', 'montant': 'montant'
        }

        df_clean = df.copy()
        for old_name, new_name in column_mapping.items():
            if old_name in df_clean.columns:
                df_clean = df_clean.rename(columns={old_name: new_name})
        
        required_columns = ['numero_compte', 'debit', 'credit']
        missing_columns = [col for col in required_columns if col not in df_clean.columns]
        
        if missing_columns:
            logger.warning(f"Colonnes manquantes: {missing_columns}")
            for col in missing_columns:
                if col in ['debit', 'credit']:
                    df_clean[col] = 0.0
                else:
                    df_clean[col] = ''
        
        for col in ['debit', 'credit']:
            if col in df_clean.columns:
                df_clean[col] = clean_numeric_column(df_clean[col])
        
        if 'numero_compte' in df_clean.columns:
            df_clean['numero_compte'] = df_clean['numero_compte'].astype(str).str.strip()
        
        if 'libelle' not in df_clean.columns:
            df_clean['libelle'] = ''
        
        return df_clean
        
    except Exception as e:
        logger.error(f"Erreur lors du nettoyage du DataFrame: {str(e)}")
        return pd.DataFrame()


def get_alerts_for_documents(documents_db, config=None):
    """Génère des alertes avec rapprochement bancaire amélioré"""
    alerts = []

    try:
        workflow = AnomalyDetectionWorkflow(config)
        document_alerts = workflow.analyze_json_files(documents_db)
        alerts.extend(document_alerts)
        
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
            'status': 'active',
            'source_file': 'Système'
        })
        score_risque = {'score': 0, 'niveau': 'ERREUR'}

    return alerts, score_risque
