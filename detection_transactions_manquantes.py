import pandas as pd
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
import logging
import re
import numpy as np
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class ConfigurationRapprochement:
    """Configuration pour le rapprochement bancaire configurée depuis le dashboard client"""
    tolerance_montant: float = 0.01  # Tolérance pour les écarts de montant en €
    tolerance_date: int = 3  # Tolérance en jours pour la correspondance des dates
    comptes_exclus: List[str] = None  # Comptes à exclure du rapprochement
    seuil_alerte_haute: float = 100.0  # Seuil pour alerte de sévérité haute
    seuil_alerte_moyenne: float = 10.0  # Seuil pour alerte de sévérité moyenne
    champs_correspondance: Dict[str, str] = None  # Mapping des champs pour la correspondance
    
    def __post_init__(self):
        if self.comptes_exclus is None:
            self.comptes_exclus = []
        if self.champs_correspondance is None:
            self.champs_correspondance = {
                'date_releve': 'date',
                'montant_releve': 'montant',
                'nature_releve': 'nature',
                'date_grand_livre': 'date',
                'debit_grand_livre': 'débit',
                'credit_grand_livre': 'crédit',
                'libelle_grand_livre': 'libellé',
                'compte_grand_livre': 'n° compte'
            }

class DetectionTransactionsManquantes:
    """
    Système de détection des transactions manquantes entre relevé bancaire et grand livre
    avec détection des écarts de montants
    """
    
    def __init__(self, config: ConfigurationRapprochement = None):
        """
        Initialise le détecteur avec la configuration du rapprochement bancaire
        
        Args:
            config: Configuration personnalisée depuis le dashboard client
        """
        self.config = config if config else ConfigurationRapprochement()
        self.alertes = []
        
    def detecter_toutes_anomalies(self, releve_bancaire: Dict, grand_livre: pd.DataFrame) -> List[Dict]:
        """
        Méthode principale qui détecte toutes les anomalies de transactions
        
        Args:
            releve_bancaire: Dictionnaire contenant les données du relevé
            grand_livre: DataFrame contenant les écritures du grand livre
            
        Returns:
            Liste des alertes détectées
        """
        logger.info("Début de la détection des anomalies de transactions")
        
        alertes = []
        
        # 1. Détection des transactions manquantes dans le grand livre
        alertes.extend(self.detecter_transactions_manquantes_grand_livre(releve_bancaire, grand_livre))
        
        # 2. Détection des transactions manquantes dans le relevé
        alertes.extend(self.detecter_transactions_manquantes_releve(releve_bancaire, grand_livre))
        
        # 3. Détection des écarts de montants
        alertes.extend(self.detecter_anomalies_montants(releve_bancaire, grand_livre))
        
        # 4. Ajout d'informations de contexte
        alertes = self._enrichir_alertes(alertes, releve_bancaire, grand_livre)
        
        logger.info(f"Détection terminée: {len(alertes)} anomalies trouvées")
        return alertes
    
    def detecter_transactions_manquantes_grand_livre(self, releve_bancaire: Dict, grand_livre: pd.DataFrame) -> List[Dict]:
        """
        Détecte les transactions présentes dans le relevé mais absentes du grand livre
        
        Args:
            releve_bancaire: Dictionnaire contenant les données du relevé
            grand_livre: DataFrame contenant les écritures du grand livre
            
        Returns:
            Liste des alertes pour transactions manquantes dans le grand livre
        """
        alertes_manquantes = []
        
        if 'operations' not in releve_bancaire:
            logger.warning("Aucune opération trouvée dans le relevé bancaire")
            return alertes_manquantes
        
        operations = releve_bancaire['operations']
        
        for i, operation in enumerate(operations):
            if not isinstance(operation, dict):
                continue
                
            montant_releve = self._nettoyer_montant(operation.get('montant', 0))
            date_operation = operation.get('date', '')
            nature_operation = operation.get('nature', '')
            
            # Recherche de correspondances dans le grand livre
            correspondances = self._chercher_correspondances_transaction(
                grand_livre, montant_releve, date_operation, nature_operation
            )
            
            if correspondances.empty:
                # Transaction manquante dans le grand livre
                severite = self._determiner_severite_montant(abs(montant_releve))
                
                alerte = {
                    'type': 'TRANSACTION_MANQUANTE_GRAND_LIVRE',
                    'severite': severite,
                    'description': f"Transaction du relevé non trouvée dans le grand livre",
                    'montant_releve': montant_releve,
                    'date_operation': date_operation,
                    'nature_operation': nature_operation,
                    'index_operation_releve': i,
                    'statut': 'A_VALIDER',
                    'date_detection': datetime.now().isoformat(),
                    'suggestions_resolution': self._generer_suggestions_manquante_gl(operation)
                }
                alertes_manquantes.append(alerte)
        
        return alertes_manquantes
    
    def detecter_transactions_manquantes_releve(self, releve_bancaire: Dict, grand_livre: pd.DataFrame) -> List[Dict]:
        """
        Détecte les transactions présentes dans le grand livre mais absentes du relevé
        
        Args:
            releve_bancaire: Dictionnaire contenant les données du relevé
            grand_livre: DataFrame contenant les écritures du grand livre
            
        Returns:
            Liste des alertes pour transactions manquantes dans le relevé
        """
        alertes_manquantes = []
        
        operations_releve = releve_bancaire.get('operations', [])
        
        # Nettoyer le grand livre
        grand_livre_clean = self._nettoyer_grand_livre(grand_livre)
        
        for index, ligne_gl in grand_livre_clean.iterrows():
            compte = ligne_gl.get(self.config.champs_correspondance['compte_grand_livre'], '')
            
            # Ignorer les comptes exclus
            if compte in self.config.comptes_exclus:
                continue
                
            debit = self._nettoyer_montant(ligne_gl.get(self.config.champs_correspondance['debit_grand_livre'], 0))
            credit = self._nettoyer_montant(ligne_gl.get(self.config.champs_correspondance['credit_grand_livre'], 0))
            montant_gl = debit if debit != 0 else credit
            
            if montant_gl == 0:
                continue
                
            date_gl = ligne_gl.get(self.config.champs_correspondance['date_grand_livre'], '')
            libelle_gl = ligne_gl.get(self.config.champs_correspondance['libelle_grand_livre'], '')
            
            # Recherche de correspondances dans le relevé
            correspondance_trouvee = self._chercher_correspondance_dans_releve(
                operations_releve, montant_gl, date_gl, libelle_gl
            )
            
            if not correspondance_trouvee:
                # Transaction manquante dans le relevé
                severite = self._determiner_severite_montant(abs(montant_gl))
                
                alerte = {
                    'type': 'TRANSACTION_MANQUANTE_RELEVE',
                    'severite': severite,
                    'compte': compte,
                    'description': f"Écriture du grand livre non trouvée dans le relevé",
                    'montant_grand_livre': montant_gl,
                    'date_grand_livre': date_gl,
                    'libelle_grand_livre': libelle_gl,
                    'index_ligne_grand_livre': index,
                    'statut': 'A_VALIDER',
                    'date_detection': datetime.now().isoformat(),
                    'suggestions_resolution': self._generer_suggestions_manquante_releve(ligne_gl)
                }
                alertes_manquantes.append(alerte)
        
        return alertes_manquantes
    
    def detecter_anomalies_montants(self, releve_bancaire: Dict, grand_livre: pd.DataFrame,
                                   tolerance: float = None) -> List[Dict]:
        """
        Détecte les écarts de montants entre relevé bancaire et grand livre
        Version corrigée du code fourni
        """
        if tolerance is None:
            tolerance = self.config.tolerance_montant
            
        alertes_montants = []

        if 'operations' not in releve_bancaire:
            return alertes_montants

        operations = releve_bancaire['operations']

        for i, operation in enumerate(operations):
            if not isinstance(operation, dict):
                continue
                
            montant_releve = self._nettoyer_montant(operation.get('montant', 0))
            nature = operation.get('nature', '')
            date_operation = operation.get('date', '')

            # Recherche dans le grand livre avec tolérance
            correspondances = self._chercher_correspondances_montant(
                grand_livre, montant_releve, tolerance
            )

            if not correspondances.empty:
                for _, ligne_gl in correspondances.iterrows():
                    debit_gl = self._nettoyer_montant(ligne_gl.get('débit', 0))
                    credit_gl = self._nettoyer_montant(ligne_gl.get('crédit', 0))
                    
                    # Correction logique: utiliser le montant non-nul du grand livre
                    montant_gl = debit_gl if debit_gl != 0 else credit_gl
                    
                    # Calculer l'écart réel
                    ecart = abs(montant_gl - montant_releve)
                    
                    # Alerte seulement si l'écart dépasse la tolérance
                    if ecart > tolerance:
                        severite = self._determiner_severite_montant(ecart)
                        
                        alerte = {
                            'type': 'ECART_MONTANT',
                            'severite': severite,
                            'compte': ligne_gl.get('n° compte', 'N/A'),
                            'description': f"Écart de montant détecté: {ecart:.2f}€",
                            'montant_releve': montant_releve,
                            'montant_grand_livre': montant_gl,
                            'ecart': ecart,
                            'date_operation': date_operation,
                            'nature_operation': nature,
                            'libelle_grand_livre': ligne_gl.get('libellé', ''),
                            'index_operation_releve': i,
                            'index_ligne_grand_livre': ligne_gl.name,
                            'statut': 'A_VALIDER',
                            'date_detection': datetime.now().isoformat(),
                            'suggestions_resolution': self._generer_suggestions_ecart_montant(ecart, montant_releve, montant_gl)
                        }
                        alertes_montants.append(alerte)

        return alertes_montants

    def _chercher_correspondances_montant(self, grand_livre: pd.DataFrame,
                                        montant: float, tolerance: float) -> pd.DataFrame:
        """
        Cherche les correspondances de montant dans le grand livre avec tolérance
        Version corrigée
        """
        if grand_livre.empty:
            return pd.DataFrame()
            
        debits = pd.to_numeric(grand_livre.get('débit', pd.Series()), errors='coerce').fillna(0)
        credits = pd.to_numeric(grand_livre.get('crédit', pd.Series()), errors='coerce').fillna(0)

        mask_debit = abs(debits - abs(montant)) <= tolerance
        mask_credit = abs(credits - abs(montant)) <= tolerance

        return grand_livre[mask_debit | mask_credit].copy()
    
    def _chercher_correspondances_transaction(self, grand_livre: pd.DataFrame, 
                                            montant: float, date: str, nature: str) -> pd.DataFrame:
        """
        Cherche les correspondances complètes de transaction dans le grand livre
        """
        if grand_livre.empty:
            return pd.DataFrame()
            
        # Recherche par montant avec tolérance
        correspondances_montant = self._chercher_correspondances_montant(
            grand_livre, montant, self.config.tolerance_montant
        )
        
        if correspondances_montant.empty:
            return pd.DataFrame()
        
        # Affiner par date si disponible
        if date and self.config.tolerance_date > 0:
            correspondances_montant = self._filtrer_par_date(
                correspondances_montant, date, self.config.tolerance_date
            )
        
        # Affiner par libellé/nature si possible
        if nature:
            correspondances_montant = self._filtrer_par_libelle(
                correspondances_montant, nature
            )
        
        return correspondances_montant
    
    def _chercher_correspondance_dans_releve(self, operations: List[Dict], 
                                           montant_gl: float, date_gl: str, libelle_gl: str) -> bool:
        """
        Cherche si une écriture du grand livre a une correspondance dans le relevé
        """
        for operation in operations:
            if not isinstance(operation, dict):
                continue
                
            montant_releve = self._nettoyer_montant(operation.get('montant', 0))
            
            # Vérification du montant avec tolérance
            if abs(abs(montant_releve) - abs(montant_gl)) <= self.config.tolerance_montant:
                
                # Vérification de la date si disponible
                if date_gl and operation.get('date'):
                    if self._dates_correspondent(operation.get('date'), date_gl):
                        return True
                else:
                    # Si pas de date disponible, considérer comme correspondance sur le montant seul
                    return True
        
        return False
    
    def _filtrer_par_date(self, df: pd.DataFrame, date_cible: str, tolerance_jours: int) -> pd.DataFrame:
        """
        Filtre les correspondances par proximité de date
        """
        try:
            date_cible_obj = self._parser_date(date_cible)
            if not date_cible_obj:
                return df
                
            mask_dates = []
            for _, row in df.iterrows():
                date_gl = self._parser_date(str(row.get('date', '')))
                if date_gl:
                    delta = abs((date_gl - date_cible_obj).days)
                    mask_dates.append(delta <= tolerance_jours)
                else:
                    mask_dates.append(True)  # Garder si pas de date dans GL
            
            return df[mask_dates] if any(mask_dates) else df
            
        except Exception as e:
            logger.warning(f"Erreur lors du filtrage par date: {e}")
            return df
    
    def _filtrer_par_libelle(self, df: pd.DataFrame, nature: str) -> pd.DataFrame:
        """
        Filtre les correspondances par similarité de libellé
        """
        if df.empty or not nature:
            return df
            
        # Recherche de mots-clés similaires
        nature_clean = self._nettoyer_texte(nature)
        mask_libelle = []
        
        for _, row in df.iterrows():
            libelle = self._nettoyer_texte(str(row.get('libellé', '')))
            if libelle and nature_clean:
                # Calcul de similarité simple
                mots_nature = set(nature_clean.split())
                mots_libelle = set(libelle.split())
                
                if mots_nature & mots_libelle:  # Intersection non vide
                    mask_libelle.append(True)
                else:
                    mask_libelle.append(False)
            else:
                mask_libelle.append(True)  # Garder si pas de libellé
        
        return df[mask_libelle] if any(mask_libelle) else df
    
    def _dates_correspondent(self, date1: str, date2: str) -> bool:
        """
        Vérifie si deux dates correspondent dans la tolérance configurée
        """
        try:
            date1_obj = self._parser_date(date1)
            date2_obj = self._parser_date(date2)
            
            if not date1_obj or not date2_obj:
                return False
                
            delta = abs((date1_obj - date2_obj).days)
            return delta <= self.config.tolerance_date
            
        except Exception:
            return False
    
    def _parser_date(self, date_str: str) -> Optional[datetime]:
        """
        Parse une date dans différents formats
        """
        if not date_str or date_str == 'N/A':
            return None
            
        formats = ['%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y', '%Y%m%d']
        
        for fmt in formats:
            try:
                return datetime.strptime(str(date_str).strip(), fmt)
            except ValueError:
                continue
        return None
    
    def _nettoyer_montant(self, montant: Any) -> float:
        """
        Nettoie et convertit un montant en float
        """
        if pd.isna(montant) or montant is None:
            return 0.0
            
        if isinstance(montant, (int, float)):
            return float(montant)
            
        # Nettoyage du texte
        montant_str = str(montant).replace(' ', '').replace(',', '.').replace('€', '').strip()
        
        try:
            return float(montant_str)
        except ValueError:
            return 0.0
    
    def _nettoyer_texte(self, texte: str) -> str:
        """
        Nettoie un texte pour la comparaison
        """
        if not texte:
            return ''
        return re.sub(r'\s+', ' ', str(texte).lower().strip())
    
    def _nettoyer_grand_livre(self, grand_livre: pd.DataFrame) -> pd.DataFrame:
        """
        Nettoie le DataFrame du grand livre
        """
        if grand_livre.empty:
            return grand_livre
            
        df_clean = grand_livre.copy()
        
        # Nettoyer les colonnes de montants
        if 'débit' in df_clean.columns:
            df_clean['débit'] = df_clean['débit'].apply(self._nettoyer_montant)
        if 'crédit' in df_clean.columns:
            df_clean['crédit'] = df_clean['crédit'].apply(self._nettoyer_montant)
            
        # Supprimer les lignes vides
        df_clean = df_clean.dropna(how='all')
        
        return df_clean
    
    def _determiner_severite_montant(self, montant: float) -> str:
        """
        Détermine la sévérité d'une alerte basée sur le montant
        """
        if montant >= self.config.seuil_alerte_haute:
            return 'HAUTE'
        elif montant >= self.config.seuil_alerte_moyenne:
            return 'MOYENNE'
        else:
            return 'FAIBLE'
    
    def _generer_suggestions_manquante_gl(self, operation: Dict) -> List[str]:
        """
        Génère des suggestions pour résoudre une transaction manquante dans le grand livre
        """
        suggestions = [
            "Vérifier si l'écriture comptable a été saisie",
            "Contrôler la date de comptabilisation",
            "Vérifier le compte comptable utilisé"
        ]
        
        montant = abs(self._nettoyer_montant(operation.get('montant', 0)))
        if montant > self.config.seuil_alerte_haute:
            suggestions.append("Montant élevé - Validation hiérarchique recommandée")
            
        return suggestions
    
    def _generer_suggestions_manquante_releve(self, ligne_gl: pd.Series) -> List[str]:
        """
        Génère des suggestions pour résoudre une transaction manquante dans le relevé
        """
        suggestions = [
            "Vérifier si l'opération apparaît sur un autre relevé",
            "Contrôler la période du relevé bancaire",
            "Vérifier s'il s'agit d'une écriture d'OD (à nouveau)"
        ]
        
        compte = str(ligne_gl.get('n° compte', ''))
        if compte.startswith('58') or compte.startswith('51'):
            suggestions.append("Compte de trésorerie - Vérifier la banque correspondante")
            
        return suggestions
    
    def _generer_suggestions_ecart_montant(self, ecart: float, montant_releve: float, montant_gl: float) -> List[str]:
        """
        Génère des suggestions pour résoudre un écart de montant
        """
        suggestions = []
        
        pourcentage_ecart = (ecart / max(abs(montant_releve), abs(montant_gl))) * 100
        
        if pourcentage_ecart < 5:
            suggestions.append("Écart faible - Vérifier les arrondis ou centimes")
        elif pourcentage_ecart < 20:
            suggestions.append("Écart modéré - Contrôler les frais bancaires ou commissions")
        else:
            suggestions.append("Écart important - Vérification approfondie nécessaire")
            
        suggestions.extend([
            "Vérifier la correspondance des dates",
            "Contrôler s'il y a plusieurs écritures pour une même opération",
            "Vérifier les écritures de régularisation"
        ])
        
        return suggestions
    
    def _enrichir_alertes(self, alertes: List[Dict], releve_bancaire: Dict, grand_livre: pd.DataFrame) -> List[Dict]:
        """
        Enrichit les alertes avec des informations de contexte
        """
        for i, alerte in enumerate(alertes):
            alerte['id'] = i + 1
            alerte['date_creation'] = datetime.now().isoformat()
            
            # Ajouter des informations sur le volume de données
            alerte['contexte'] = {
                'nb_operations_releve': len(releve_bancaire.get('operations', [])),
                'nb_lignes_grand_livre': len(grand_livre),
                'periode_releve': releve_bancaire.get('informations_bancaires', {}).get('periode_releve', {}),
                'tolerance_utilisee': self.config.tolerance_montant
            }
            
        return alertes
    
    def generer_rapport_synthese(self, alertes: List[Dict]) -> Dict[str, Any]:
        """
        Génère un rapport de synthèse des anomalies détectées
        """
        rapport = {
            'resume': {
                'total_alertes': len(alertes),
                'alertes_par_type': {},
                'alertes_par_severite': {},
                'montant_total_ecarts': 0.0
            },
            'recommandations': [],
            'prochaines_actions': [],
            'date_generation': datetime.now().isoformat()
        }
        
        # Statistiques par type
        for alerte in alertes:
            type_alerte = alerte.get('type', 'INCONNU')
            severite = alerte.get('severite', 'INCONNUE')
            
            rapport['resume']['alertes_par_type'][type_alerte] = rapport['resume']['alertes_par_type'].get(type_alerte, 0) + 1
            rapport['resume']['alertes_par_severite'][severite] = rapport['resume']['alertes_par_severite'].get(severite, 0) + 1
            
            # Cumul des écarts
            if 'ecart' in alerte:
                rapport['resume']['montant_total_ecarts'] += alerte['ecart']
        
        # Recommandations générales
        if rapport['resume']['alertes_par_severite'].get('HAUTE', 0) > 0:
            rapport['recommandations'].append("Traiter en priorité les alertes de sévérité HAUTE")
            
        if rapport['resume']['montant_total_ecarts'] > 1000:
            rapport['recommandations'].append("Montant total des écarts élevé - Audit approfondi recommandé")
            
        return rapport
    
    def sauvegarder_alertes(self, alertes: List[Dict], chemin_fichier: str):
        """
        Sauvegarde les alertes dans un fichier JSON
        """
        try:
            with open(chemin_fichier, 'w', encoding='utf-8') as f:
                json.dump({
                    'alertes': alertes,
                    'configuration': {
                        'tolerance_montant': self.config.tolerance_montant,
                        'tolerance_date': self.config.tolerance_date,
                        'comptes_exclus': self.config.comptes_exclus
                    },
                    'date_export': datetime.now().isoformat()
                }, f, indent=2, ensure_ascii=False)
                
            logger.info(f"Alertes sauvegardées dans {chemin_fichier}")
            
        except Exception as e:
            logger.error(f"Erreur lors de la sauvegarde: {e}")


def exemple_utilisation():
    """
    Exemple d'utilisation du système de détection
    """
    # Configuration personnalisée
    config = ConfigurationRapprochement(
        tolerance_montant=0.05,  # 5 centimes de tolérance
        tolerance_date=2,        # 2 jours de tolérance
        seuil_alerte_haute=500.0,
        comptes_exclus=['512000', '531000']  # Comptes de virements internes
    )
    
    # Initialisation du détecteur
    detecteur = DetectionTransactionsManquantes(config)
    
    # Données d'exemple
    releve_exemple = {
        'operations': [
            {'date': '15/01/2024', 'montant': 1500.00, 'nature': 'VIREMENT CLIENT ABC'},
            {'date': '16/01/2024', 'montant': -250.50, 'nature': 'PRELEVEMENT EDF'},
            {'date': '17/01/2024', 'montant': 3000.00, 'nature': 'DEPOT CHEQUE'}
        ]
    }
    
    grand_livre_exemple = pd.DataFrame([
        {'date': '15/01/2024', 'n° compte': '411000', 'libellé': 'CLIENT ABC', 'débit': 1500.00, 'crédit': 0},
        {'date': '16/01/2024', 'n° compte': '626100', 'libellé': 'ELECTRICITE', 'débit': 0, 'crédit': 250.45},
        {'date': '18/01/2024', 'n° compte': '512000', 'libellé': 'BANQUE', 'débit': 2000.00, 'crédit': 0}
    ])
    
    # Détection des anomalies
    alertes = detecteur.detecter_toutes_anomalies(releve_exemple, grand_livre_exemple)
    
    # Génération du rapport
    rapport = detecteur.generer_rapport_synthese(alertes)
    
    print("=== RAPPORT DE SYNTHÈSE ===")
    print(f"Total alertes: {rapport['resume']['total_alertes']}")
    print(f"Alertes par type: {rapport['resume']['alertes_par_type']}")
    print(f"Montant total écarts: {rapport['resume']['montant_total_ecarts']:.2f}€")
    
    return alertes, rapport


if __name__ == "__main__":
    # Test du système
    alertes, rapport = exemple_utilisation()
    
    print("\n=== DÉTAIL DES ALERTES ===")
    for alerte in alertes:
        print(f"Type: {alerte['type']}")
        print(f"Sévérité: {alerte['severite']}")
        print(f"Description: {alerte['description']}")
        print("---")