import json
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict
import re

logger = logging.getLogger(__name__)

class GrandLivreProcessor:
    """Processeur pour analyser et calculer les caractéristiques du grand livre"""
    
    def __init__(self):
        self.data = {}
        self.characteristics = {}
        self.compte_patterns = {
            'banque': r'^512\d*',
            'clients': r'^411\d*',
            'fournisseurs': r'^401\d*',
            'tva_deductible': r'^445661\d*',
            'tva_collectee': r'^445711\d*',
            'ventes': r'^70\d*',
            'achats': r'^60\d*',
            'charges': r'^6\d*',
            'immobilisations': r'^2\d*',
            'stocks': r'^3\d*',
            'capitaux': r'^1\d*'
        }
    
    def process_grandlivre_json(self, json_file_path: str) -> Dict[str, Any]:
        """Traite un fichier JSON de grand livre et calcule les caractéristiques"""
        try:
            with open(json_file_path, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
            
            # Extraire les écritures
            ecritures = self._extract_ecritures()
            
            # Calculer les caractéristiques
            self.characteristics = self._calculate_characteristics(ecritures)
            
            # Ajouter les informations du fichier
            self.characteristics['fichier_source'] = os.path.basename(json_file_path)
            self.characteristics['date_traitement'] = datetime.now().isoformat()
            
            logger.info(f"Traitement terminé pour {json_file_path}: {len(ecritures)} écritures analysées")
            
            return self.characteristics
            
        except Exception as e:
            logger.error(f"Erreur lors du traitement du grand livre {json_file_path}: {str(e)}")
            return self._get_empty_characteristics()
    
    def _extract_ecritures(self) -> List[Dict[str, Any]]:
        """Extrait les écritures du JSON"""
        ecritures = []
        
        # Différents formats possibles
        raw_ecritures = self.data.get('ecritures_comptables', 
                                    self.data.get('ecritures', 
                                                self.data.get('lignes', [])))
        
        if not isinstance(raw_ecritures, list):
            return ecritures
        
        for ecriture in raw_ecritures:
            if isinstance(ecriture, dict):
                processed_ecriture = self._normalize_ecriture(ecriture)
                if processed_ecriture:
                    ecritures.append(processed_ecriture)
        
        return ecritures
    
    def _normalize_ecriture(self, ecriture: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Normalise une écriture comptable"""
        try:
            # Normaliser les noms de colonnes
            normalized = {}
            
            # Numéro de compte
            compte_keys = ['n° compte', 'numero_compte', 'compte', 'N° Compte']
            for key in compte_keys:
                if key in ecriture:
                    normalized['numero_compte'] = str(ecriture[key]).strip()
                    break
            
            # Libellé
            libelle_keys = ['libellé', 'libelle', 'description', 'Libellé']
            for key in libelle_keys:
                if key in ecriture:
                    normalized['libelle'] = str(ecriture[key]).strip()
                    break
            
            # Date
            date_keys = ['date', 'Date', 'DATE']
            for key in date_keys:
                if key in ecriture:
                    normalized['date'] = self._normalize_date(ecriture[key])
                    break
            
            # Débit
            debit_keys = ['débit', 'debit', 'DÉBIT']
            for key in debit_keys:
                if key in ecriture:
                    normalized['debit'] = self._normalize_amount(ecriture[key])
                    break
            
            # Crédit
            credit_keys = ['crédit', 'credit', 'CRÉDIT']
            for key in credit_keys:
                if key in ecriture:
                    normalized['credit'] = self._normalize_amount(ecriture[key])
                    break
            
            # Vérifier que les champs essentiels sont présents
            if not normalized.get('numero_compte'):
                return None
            
            # Valeurs par défaut
            normalized.setdefault('libelle', '')
            normalized.setdefault('debit', 0.0)
            normalized.setdefault('credit', 0.0)
            normalized.setdefault('date', '')
            
            # Calculer le montant net
            normalized['montant_net'] = normalized['debit'] - normalized['credit']
            
            return normalized
            
        except Exception as e:
            logger.warning(f"Erreur normalisation écriture: {str(e)}")
            return None
    
    def _normalize_amount(self, amount) -> float:
        """Normalise un montant"""
        if amount is None or amount == '' or amount == 'N/A':
            return 0.0
        
        try:
            # Convertir en string et nettoyer
            amount_str = str(amount).strip()
            
            # Supprimer les caractères non numériques sauf . , -
            amount_str = re.sub(r'[^\d\.,\-]', '', amount_str)
            
            # Supprimer les espaces
            amount_str = amount_str.replace(' ', '')
            
            if not amount_str or amount_str == '-':
                return 0.0
            
            # Gérer les formats français (virgule décimale)
            if ',' in amount_str and '.' in amount_str:
                # Format avec virgule et point
                if amount_str.rfind(',') > amount_str.rfind('.'):
                    # Format européen : 1.234,56
                    amount_str = amount_str.replace('.', '').replace(',', '.')
                else:
                    # Format anglais : 1,234.56
                    amount_str = amount_str.replace(',', '')
            elif ',' in amount_str:
                # Seulement une virgule
                comma_pos = amount_str.rfind(',')
                if len(amount_str) - comma_pos - 1 <= 2:
                    # Virgule décimale
                    amount_str = amount_str.replace(',', '.')
                else:
                    # Virgule milliers
                    amount_str = amount_str.replace(',', '')
            
            return float(amount_str)
            
        except (ValueError, TypeError):
            return 0.0
    
    def _normalize_date(self, date_str) -> str:
        """Normalise une date"""
        if not date_str or date_str == 'N/A':
            return ''
        
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
        
        return date_str
    
    def _calculate_characteristics(self, ecritures: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calcule les caractéristiques du grand livre"""
        characteristics = {}
        
        # Statistiques générales
        characteristics['nombre_ecritures'] = len(ecritures)
        characteristics['total_debit'] = sum(e['debit'] for e in ecritures)
        characteristics['total_credit'] = sum(e['credit'] for e in ecritures)
        characteristics['balance'] = characteristics['total_debit'] - characteristics['total_credit']
        
        # Analyser par type de compte
        comptes_par_type = self._classify_accounts(ecritures)
        characteristics['comptes_par_type'] = comptes_par_type
        
        # Calculer les soldes par type
        soldes_par_type = self._calculate_soldes_par_type(comptes_par_type)
        characteristics['soldes_par_type'] = soldes_par_type
        
        # Analyser les mouvements
        mouvements = self._analyze_mouvements(ecritures)
        characteristics['analyse_mouvements'] = mouvements
        
        # Calculer les ratios
        ratios = self._calculate_ratios(ecritures, soldes_par_type)
        characteristics['ratios'] = ratios
        
        # Analyser les dates
        analyse_dates = self._analyze_dates(ecritures)
        characteristics['analyse_dates'] = analyse_dates
        
        # Détection d'anomalies
        anomalies = self._detect_anomalies(ecritures)
        characteristics['anomalies'] = anomalies
        
        # Statistiques détaillées par compte
        details_comptes = self._get_detailed_account_stats(ecritures)
        characteristics['details_comptes'] = details_comptes
        
        return characteristics
    
    def _classify_accounts(self, ecritures: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Classe les comptes par type"""
        comptes_par_type = defaultdict(list)
        
        for ecriture in ecritures:
            numero_compte = ecriture['numero_compte']
            
            # Déterminer le type de compte
            compte_type = self._determine_account_type(numero_compte)
            comptes_par_type[compte_type].append(ecriture)
        
        return dict(comptes_par_type)
    
    def _determine_account_type(self, numero_compte: str) -> str:
        """Détermine le type d'un compte"""
        for type_compte, pattern in self.compte_patterns.items():
            if re.match(pattern, numero_compte):
                return type_compte
        return 'autres'
    
    def _calculate_soldes_par_type(self, comptes_par_type: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Dict[str, float]]:
        """Calcule les soldes par type de compte"""
        soldes = {}
        
        for type_compte, ecritures in comptes_par_type.items():
            total_debit = sum(e['debit'] for e in ecritures)
            total_credit = sum(e['credit'] for e in ecritures)
            solde = total_debit - total_credit
            
            soldes[type_compte] = {
                'total_debit': total_debit,
                'total_credit': total_credit,
                'solde': solde,
                'nombre_ecritures': len(ecritures)
            }
        
        return soldes
    
    def _analyze_mouvements(self, ecritures: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyse les mouvements"""
        mouvements = {
            'plus_gros_debit': 0,
            'plus_gros_credit': 0,
            'moyenne_debit': 0,
            'moyenne_credit': 0,
            'ecritures_importantes': [],
            'comptes_les_plus_actifs': []
        }
        
        if not ecritures:
            return mouvements
        
        # Statistiques de base
        debits = [e['debit'] for e in ecritures if e['debit'] > 0]
        credits = [e['credit'] for e in ecritures if e['credit'] > 0]
        
        if debits:
            mouvements['plus_gros_debit'] = max(debits)
            mouvements['moyenne_debit'] = np.mean(debits)
        
        if credits:
            mouvements['plus_gros_credit'] = max(credits)
            mouvements['moyenne_credit'] = np.mean(credits)
        
        # Écritures importantes (>= 10000€)
        seuil_important = 10000
        ecritures_importantes = [
            e for e in ecritures 
            if abs(e['montant_net']) >= seuil_important
        ]
        
        mouvements['ecritures_importantes'] = [
            {
                'numero_compte': e['numero_compte'],
                'libelle': e['libelle'][:50],
                'montant': e['montant_net'],
                'date': e['date']
            }
            for e in ecritures_importantes[:10]  # Top 10
        ]
        
        # Comptes les plus actifs
        activite_comptes = defaultdict(int)
        for ecriture in ecritures:
            activite_comptes[ecriture['numero_compte']] += 1
        
        comptes_actifs = sorted(activite_comptes.items(), key=lambda x: x[1], reverse=True)
        mouvements['comptes_les_plus_actifs'] = [
            {'numero_compte': compte, 'nombre_ecritures': count}
            for compte, count in comptes_actifs[:10]
        ]
        
        return mouvements
    
    def _calculate_ratios(self, ecritures: List[Dict[str, Any]], soldes_par_type: Dict[str, Dict[str, float]]) -> Dict[str, float]:
        """Calcule les ratios financiers"""
        ratios = {}
        
        try:
            # Ratio d'équilibre
            total_debit = sum(e['debit'] for e in ecritures)
            total_credit = sum(e['credit'] for e in ecritures)
            
            if total_credit > 0:
                ratios['ratio_equilibre'] = total_debit / total_credit
            else:
                ratios['ratio_equilibre'] = 0
            
            # Ratio de liquidité (si on a des comptes de banque et de fournisseurs)
            solde_banque = soldes_par_type.get('banque', {}).get('solde', 0)
            solde_fournisseurs = abs(soldes_par_type.get('fournisseurs', {}).get('solde', 0))
            
            if solde_fournisseurs > 0:
                ratios['ratio_liquidite'] = solde_banque / solde_fournisseurs
            else:
                ratios['ratio_liquidite'] = 0
            
            # Ratio d'endettement
            solde_capitaux = soldes_par_type.get('capitaux', {}).get('solde', 0)
            
            if solde_capitaux > 0:
                ratios['ratio_endettement'] = solde_fournisseurs / solde_capitaux
            else:
                ratios['ratio_endettement'] = 0
            
            # Ratio de rotation des stocks
            solde_stocks = soldes_par_type.get('stocks', {}).get('solde', 0)
            solde_achats = soldes_par_type.get('achats', {}).get('solde', 0)
            
            if solde_stocks > 0 and solde_achats > 0:
                ratios['ratio_rotation_stocks'] = solde_achats / solde_stocks
            else:
                ratios['ratio_rotation_stocks'] = 0
            
        except Exception as e:
            logger.warning(f"Erreur calcul ratios: {str(e)}")
        
        return ratios
    
    def _analyze_dates(self, ecritures: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyse les dates des écritures"""
        analyse = {
            'periode_debut': None,
            'periode_fin': None,
            'duree_jours': 0,
            'repartition_mensuelle': {},
            'ecritures_sans_date': 0
        }
        
        dates_valides = []
        
        for ecriture in ecritures:
            date_str = ecriture.get('date', '')
            if date_str and date_str != '':
                try:
                    date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                    dates_valides.append(date_obj)
                except ValueError:
                    analyse['ecritures_sans_date'] += 1
            else:
                analyse['ecritures_sans_date'] += 1
        
        if dates_valides:
            dates_valides.sort()
            analyse['periode_debut'] = dates_valides[0].strftime('%Y-%m-%d')
            analyse['periode_fin'] = dates_valides[-1].strftime('%Y-%m-%d')
            analyse['duree_jours'] = (dates_valides[-1] - dates_valides[0]).days
            
            # Répartition mensuelle
            repartition = defaultdict(int)
            for date_obj in dates_valides:
                mois_key = date_obj.strftime('%Y-%m')
                repartition[mois_key] += 1
            
            analyse['repartition_mensuelle'] = dict(repartition)
        
        return analyse
    
    def _detect_anomalies(self, ecritures: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Détecte les anomalies dans les écritures"""
        anomalies = []
        
        # Détection d'écritures dupliquées
        ecritures_vues = set()
        for ecriture in ecritures:
            signature = f"{ecriture['numero_compte']}_{ecriture['date']}_{ecriture['montant_net']}"
            if signature in ecritures_vues:
                anomalies.append({
                    'type': 'doublon',
                    'description': f"Écriture dupliquée détectée pour le compte {ecriture['numero_compte']}",
                    'compte': ecriture['numero_compte'],
                    'montant': ecriture['montant_net'],
                    'date': ecriture['date']
                })
            else:
                ecritures_vues.add(signature)
        
        # Détection de montants anormalement élevés
        montants = [abs(e['montant_net']) for e in ecritures if e['montant_net'] != 0]
        if montants:
            seuil_anomalie = np.percentile(montants, 95)  # 95e percentile
            
            for ecriture in ecritures:
                if abs(ecriture['montant_net']) > seuil_anomalie:
                    anomalies.append({
                        'type': 'montant_eleve',
                        'description': f"Montant anormalement élevé: {ecriture['montant_net']:.2f}€",
                        'compte': ecriture['numero_compte'],
                        'montant': ecriture['montant_net'],
                        'date': ecriture['date']
                    })
        
        # Détection de comptes inhabituels
        comptes_usuels = set()
        for pattern in self.compte_patterns.values():
            comptes_usuels.add(pattern)
        
        for ecriture in ecritures:
            compte = ecriture['numero_compte']
            if not any(re.match(pattern, compte) for pattern in self.compte_patterns.values()):
                anomalies.append({
                    'type': 'compte_inhabituel',
                    'description': f"Compte inhabituel détecté: {compte}",
                    'compte': compte,
                    'montant': ecriture['montant_net'],
                    'date': ecriture['date']
                })
        
        return anomalies[:20]  # Limiter à 20 anomalies
    
    def _get_detailed_account_stats(self, ecritures: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Obtient les statistiques détaillées par compte"""
        stats_par_compte = defaultdict(lambda: {
            'nombre_ecritures': 0,
            'total_debit': 0,
            'total_credit': 0,
            'solde': 0,
            'premiere_ecriture': None,
            'derniere_ecriture': None,
            'libelle_principal': ''
        })
        
        # Compter les libellés par compte
        libelles_par_compte = defaultdict(lambda: defaultdict(int))
        
        for ecriture in ecritures:
            compte = ecriture['numero_compte']
            stats = stats_par_compte[compte]
            
            stats['nombre_ecritures'] += 1
            stats['total_debit'] += ecriture['debit']
            stats['total_credit'] += ecriture['credit']
            stats['solde'] = stats['total_debit'] - stats['total_credit']
            
            # Première et dernière écriture
            date_ecriture = ecriture.get('date', '')
            if date_ecriture:
                if not stats['premiere_ecriture'] or date_ecriture < stats['premiere_ecriture']:
                    stats['premiere_ecriture'] = date_ecriture
                if not stats['derniere_ecriture'] or date_ecriture > stats['derniere_ecriture']:
                    stats['derniere_ecriture'] = date_ecriture
            
            # Compter les libellés
            if ecriture['libelle']:
                libelles_par_compte[compte][ecriture['libelle']] += 1
        
        # Déterminer le libellé principal pour chaque compte
        for compte, stats in stats_par_compte.items():
            if compte in libelles_par_compte:
                libelle_principal = max(libelles_par_compte[compte].items(), key=lambda x: x[1])[0]
                stats['libelle_principal'] = libelle_principal
        
        return dict(stats_par_compte)
    
    def _get_empty_characteristics(self) -> Dict[str, Any]:
        """Retourne des caractéristiques vides en cas d'erreur"""
        return {
            'nombre_ecritures': 0,
            'total_debit': 0,
            'total_credit': 0,
            'balance': 0,
            'comptes_par_type': {},
            'soldes_par_type': {},
            'analyse_mouvements': {},
            'ratios': {},
            'analyse_dates': {},
            'anomalies': [],
            'details_comptes': {},
            'fichier_source': '',
            'date_traitement': datetime.now().isoformat(),
            'erreur': 'Erreur lors du traitement'
        }
    
    def export_to_json(self, output_path: str) -> bool:
        """Exporte les caractéristiques vers un fichier JSON"""
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(self.characteristics, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"Erreur lors de l'export: {str(e)}")
            return False
    
    def get_summary(self) -> Dict[str, Any]:
        """Retourne un résumé des caractéristiques"""
        if not self.characteristics:
            return {}
        
        return {
            'nombre_ecritures': self.characteristics.get('nombre_ecritures', 0),
            'balance': self.characteristics.get('balance', 0),
            'nombre_comptes': len(self.characteristics.get('details_comptes', {})),
            'periode': {
                'debut': self.characteristics.get('analyse_dates', {}).get('periode_debut', ''),
                'fin': self.characteristics.get('analyse_dates', {}).get('periode_fin', '')
            },
            'nombre_anomalies': len(self.characteristics.get('anomalies', [])),
            'types_comptes': list(self.characteristics.get('soldes_par_type', {}).keys())
        }

# Fonction utilitaire pour traiter un fichier
def process_grandlivre_file(json_file_path: str) -> Dict[str, Any]:
    """Fonction utilitaire pour traiter un fichier de grand livre"""
    processor = GrandLivreProcessor()
    return processor.process_grandlivre_json(json_file_path)

# Fonction pour traiter plusieurs fichiers
def process_multiple_grandlivre_files(json_file_paths: List[str]) -> Dict[str, Dict[str, Any]]:
    """Traite plusieurs fichiers de grand livre"""
    results = {}
    
    for file_path in json_file_paths:
        try:
            result = process_grandlivre_file(file_path)
            results[os.path.basename(file_path)] = result
        except Exception as e:
            logger.error(f"Erreur traitement {file_path}: {str(e)}")
            results[os.path.basename(file_path)] = {
                'erreur': str(e),
                'fichier_source': os.path.basename(file_path)
            }
    
    return results
