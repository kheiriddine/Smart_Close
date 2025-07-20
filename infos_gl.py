import json
import re
import pandas as pd
from datetime import datetime
from typing import Dict, List, Any, Tuple
import logging
import os

logger = logging.getLogger(__name__)

def extract_client_fournisseur_name(libelle: str) -> str:
    """
    Extrait le nom du client ou fournisseur depuis un libellé.
    
    Exemples :
    - "Encaissement FAC2025010102 - InfoVista Ltd" → "InfoVista Ltd"
    - "Chèque encaissé N°6593816 - Crédit Mutuel" → "Crédit Mutuel"
    - "411 - InfoVista Ltd (411)" → "InfoVista Ltd"
    """
    import re

    # Essayer d'extraire la partie après le dernier tiret " - "
    if " - " in libelle:
        name_part = libelle.split(" - ")[-1].strip()
    else:
        name_part = libelle.strip()

    # Supprimer les annotations de compte type "(411)", "(401)", etc.
    name_part = re.sub(r'\(\s*\d{3,}\s*\)', '', name_part)

    # Nettoyer les caractères spéciaux en fin ou début
    name_part = re.sub(r'^[^\w&]+|[^\w&.-]+$', '', name_part).strip()

    # Supprimer doublons ou notes entre parenthèses
    name_part = re.sub(r'\s{2,}', ' ', name_part)

    # Si le nom est raisonnablement long, retourner
    if name_part and len(name_part) > 2:
        return name_part

    return "Inconnu"

def parse_amount(value) -> float:
    """
    Parse une valeur en montant numérique
    """
    if isinstance(value, (int, float)):
        return float(value)
    
    if isinstance(value, str):
        # Supprimer les espaces et remplacer la virgule par un point
        value = value.replace(' ', '').replace(',', '.').replace('€', '').strip()
        # Supprimer les caractères non numériques sauf le point et le signe moins
        value = re.sub(r'[^\d.-]', '', value)
        
        try:
            return float(value)
        except ValueError:
            return 0.0
    
    return 0.0

def analyze_grandlivre_json(json_file_path: str) -> Dict[str, Any]:
    """
    Analyse un fichier JSON de Grand Livre généré par le pipeline

    Args:
        json_file_path (str): Chemin vers le fichier JSON du Grand Livre

    Returns:
        Dict contenant toutes les informations comptables extraites
    """
    logger.info(f"Analyse du fichier Grand Livre: {json_file_path}")

    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Extraire les informations générales
        info_generales = data.get('informations_generales', {})
        nom_banque = info_generales.get('nom_banque', 'Banque inconnue')
        solde_depart = parse_amount(info_generales.get('solde_depart', 0))

        # Extraire les écritures comptables
        ecritures = data.get('ecritures_comptables', [])

        if not ecritures:
            logger.warning("Aucune écriture comptable trouvée dans le fichier JSON")
            return create_empty_analysis()

        # Convertir en DataFrame pour faciliter l'analyse
        df_table = pd.DataFrame(ecritures)

        # Nettoyer les colonnes débit et crédit
        df_table["débit"] = pd.to_numeric(
            df_table["débit"].astype(str).str.replace(',', '').str.replace('€', '').str.strip(),
            errors='coerce'
        ).fillna(0)
        df_table["crédit"] = pd.to_numeric(
            df_table["crédit"].astype(str).str.replace(',', '').str.replace('€', '').str.strip(),
            errors='coerce'
        ).fillna(0)

        # Total Débit et Crédit
        total_debit = df_table["débit"].sum()
        total_credit = df_table["crédit"].sum()

        # Analyse des comptes bancaires (512)
        df_banque = df_table[df_table["n° compte"].astype(str).str.startswith("512")]
        credit_512 = df_banque["crédit"].sum()
        debit_512 = df_banque["débit"].sum()
        solde_bancaire = solde_depart - credit_512 + debit_512

        # Créance clients (411) = débit - crédit
        df_411 = df_table[df_table["n° compte"].astype(str).str.startswith("411")]
        creances_clients = df_411["débit"].sum() - df_411["crédit"].sum()

        # Dette fournisseurs (401) = crédit - débit
        df_401 = df_table[df_table["n° compte"].astype(str).str.startswith("401")]
        dettes_fournisseurs = df_401["crédit"].sum() - df_401["débit"].sum()

        # TVA collectée (44571) — crédit
        tva_collectee = df_table[df_table["n° compte"].astype(str).str.startswith("44571")]["crédit"].sum()

        # TVA déductible (44566) — débit
        tva_deductible = df_table[df_table["n° compte"].astype(str).str.startswith("44566")]["débit"].sum()

        # Chiffre d'affaires (706) — crédit
        chiffre_affaires = df_table[df_table["n° compte"].astype(str).str.startswith("706")]["crédit"].sum()

        # Charges (comptes 6xx) — débit
        charges = df_table[df_table["n° compte"].astype(str).str.startswith("6")]["débit"].sum()

        # Analyse détaillée par type de compte
        comptes_details = analyze_comptes_details(df_table)

        # Construire le résultat
        result = {
            'total_ecritures': len(ecritures),
            'total_debit': total_debit,
            'total_credit': total_credit,
            'balance': total_credit - total_debit,
            'solde_banque': solde_bancaire,
            'tva_deductible': tva_deductible,
            'tva_collectee': tva_collectee,
            'creances_clients': max(0, creances_clients),  # Ne peut pas être négatif
            'dettes_fournisseurs': max(0, dettes_fournisseurs),  # Ne peut pas être négatif
            'chiffre_affaires': chiffre_affaires,
            'charges': charges,
            'informations_generales': {
                'nom_banque': nom_banque,
                'solde_depart': solde_depart,
                'nb_ecritures_clients': len(df_411),
                'nb_ecritures_fournisseurs': len(df_401),
            },
            'comptes_details': comptes_details,
            'resume_comptable': {
                'resultat_brut': chiffre_affaires - charges,
                'tva_a_declarer': tva_collectee - tva_deductible,
                'liquidite_disponible': solde_bancaire
            }
        }

        logger.info(f"Analyse terminée: {result} écritures, "
                    f"Total débits: {result['total_debit']:.2f}€, "
                    f"Total crédits: {result['total_credit']:.2f}€")

        return result

    except Exception as e:
        logger.error(f"Erreur lors de l'analyse du fichier Grand Livre: {str(e)}")
        return create_empty_analysis()


def analyze_comptes_details(df_table: pd.DataFrame) -> Dict[str, List[Dict]]:
    """
    Analyse détaillée des comptes par catégorie
    """
    comptes_details = {
        'banque': [],
        'clients': [],
        'fournisseurs': [],
        'tva': []
    }
    
    # Grouper par numéro de compte
    comptes_groupes = df_table.groupby('n° compte').agg({
        'libellé': 'first',
        'débit': 'sum',
        'crédit': 'sum'
    }).reset_index()
    
    for _, compte in comptes_groupes.iterrows():
        numero_compte = str(compte['n° compte'])
        libelle = compte['libellé']
        debit = compte['débit']
        credit = compte['crédit']
        solde = credit - debit
        
        compte_info = {
            'numero': numero_compte,
            'libelle': libelle,
            'debit': debit,
            'credit': credit,
            'solde': solde
        }
        
        # Comptes bancaires (512)
        if numero_compte.startswith('512'):
            comptes_details['banque'].append(compte_info)
        
        # Comptes clients (411)
        elif numero_compte.startswith('411'):
            nom_client = extract_client_fournisseur_name(libelle)
            compte_info['nom'] = nom_client
            compte_info['libelle'] = f"{nom_client} ({numero_compte})"
            compte_info['solde'] = debit - credit  # Pour les clients, le solde débiteur représente une créance
            comptes_details['clients'].append(compte_info)
        
        # Comptes fournisseurs (401)
        elif numero_compte.startswith('401'):
            nom_fournisseur = extract_client_fournisseur_name(libelle)
            compte_info['nom'] = nom_fournisseur
            compte_info['libelle'] = f"{nom_fournisseur} ({numero_compte})"
            comptes_details['fournisseurs'].append(compte_info)
        
        # Comptes TVA (445)
        elif numero_compte.startswith('445'):
            tva_type = 'autre'
            if '44566' in numero_compte or 'deductible' in libelle.lower():
                tva_type = 'deductible'
            elif '44571' in numero_compte or 'collecte' in libelle.lower():
                tva_type = 'collectee'
            
            compte_info['type'] = tva_type
            comptes_details['tva'].append(compte_info)
    
    return comptes_details

def create_empty_analysis() -> Dict[str, Any]:
    """
    Crée une structure d'analyse vide en cas d'erreur
    """
    return {
        'total_ecritures': 0,
        'total_debit': 0,
        'total_credit': 0,
        'balance': 0,
        'solde_banque': 0,
        'tva_deductible': 0,
        'tva_collectee': 0,
        'creances_clients': 0,
        'dettes_fournisseurs': 0,
        'chiffre_affaires': 0,
        'charges': 0,
        'informations_generales': {
            'nom_banque': 'Aucune donnée',
            'solde_depart': 0,
            'nb_factures_clients': 0,
            'nb_factures_fournisseurs': 0,
            'encaissements': 0
        },
        'comptes_details': {
            'banque': [],
            'clients': [],
            'fournisseurs': [],
            'tva': []
        },
        'resume_comptable': {
            'resultat_brut': 0,
            'tva_a_declarer': 0,
            'liquidite_disponible': 0
        }
    }

def find_grandlivre_json_files(uploads_folder: str = 'uploads') -> List[str]:
    """
    Trouve tous les fichiers JSON de Grand Livre dans le dossier uploads
    Recherche spécifiquement les fichiers contenant "Grand_livre" dans le nom
    """
    json_files = []
    
    if not os.path.exists(uploads_folder):
        logger.warning(f"Dossier uploads non trouvé: {uploads_folder}")
        return json_files
    
    for filename in os.listdir(uploads_folder):
        # Chercher spécifiquement les fichiers Grand Livre
        if (filename.startswith('Output_') and 
            filename.endswith('.json') and 
            'Grand_livre' in filename):
            
            file_path = os.path.join(uploads_folder, filename)
            try:
                # Vérifier que c'est bien un fichier de Grand Livre valide
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Vérifier si c'est un Grand Livre (contient ecritures_comptables)
                    if 'ecritures_comptables' in data:
                        json_files.append(file_path)
                        logger.info(f"Fichier Grand Livre trouvé: {filename}")
            except Exception as e:
                logger.warning(f"Erreur lecture fichier {filename}: {str(e)}")
    
    logger.info(f"Total fichiers Grand Livre trouvés: {len(json_files)}")
    return json_files

def get_consolidated_grandlivre_data(uploads_folder: str = 'uploads') -> Dict[str, Any]:
    """
    Récupère les données du fichier Grand Livre le plus récent
    """
    json_files = find_grandlivre_json_files(uploads_folder)
    
    if not json_files:
        logger.info("Aucun fichier Grand Livre trouvé")
        return create_empty_analysis()
    
    # Prendre le fichier le plus récent (basé sur le nom de fichier avec timestamp)
    latest_file = max(json_files, key=lambda x: os.path.getmtime(x))
    logger.info(f"Utilisation du fichier Grand Livre le plus récent: {os.path.basename(latest_file)}")
    
    return analyze_grandlivre_json(latest_file)

def get_dashboard_summary(uploads_folder: str = 'uploads') -> Dict[str, Any]:
    """
    Génère un résumé pour le dashboard principal
    """
    grandlivre_data = get_consolidated_grandlivre_data(uploads_folder)
    
    summary = {
        'grand_livre': {
            'total_ecritures': grandlivre_data['total_ecritures'],
            'total_debit': grandlivre_data['total_debit'],
            'total_credit': grandlivre_data['total_credit'],
            'balance': grandlivre_data['balance'],
            'solde_banque_512200': grandlivre_data['solde_banque'],
            'tva_deductible_44566': grandlivre_data['tva_deductible'],
            'tva_collectee_44571': grandlivre_data['tva_collectee']
        },
        'tableaux_bord': {
            'tresorerie': {
                'nb_comptes_banque': len(grandlivre_data['comptes_details']['banque']),
                'solde_total': grandlivre_data['solde_banque']
            },
            'clients': {
                'nb_comptes_clients': len(grandlivre_data['comptes_details']['clients']),
                'creances_totales': grandlivre_data['creances_clients']
            },
            'fournisseurs': {
                'nb_comptes_fournisseurs': len(grandlivre_data['comptes_details']['fournisseurs']),
                'dettes_totales': grandlivre_data['dettes_fournisseurs']
            },
            'tva': {
                'nb_comptes_tva': len(grandlivre_data['comptes_details']['tva']),
                'tva_a_declarer': grandlivre_data['tva_collectee'] - grandlivre_data['tva_deductible']
            }
        }
    }
    
    return summary

def get_tresorerie_details(uploads_folder: str = 'uploads') -> Dict[str, Any]:
    """
    Récupère les détails de trésorerie pour le dashboard spécialisé
    """
    grandlivre_data = get_consolidated_grandlivre_data(uploads_folder)
    
    tresorerie_details = {
        'solde_banque_principal': grandlivre_data['solde_banque'],
        'total_debit': grandlivre_data['total_debit'],
        'total_credit': grandlivre_data['total_credit'],
        'comptes_bancaires': grandlivre_data['comptes_details']['banque'],
        'flux_tresorerie': {
            'entrees': grandlivre_data['total_credit'],
            'sorties': grandlivre_data['total_debit'],
            'solde_net': grandlivre_data['total_credit'] - grandlivre_data['total_debit']
        }
    }
    
    return tresorerie_details

def get_clients_details(uploads_folder: str = 'uploads') -> Dict[str, Any]:
    """
    Récupère les détails clients pour le dashboard spécialisé
    """
    grandlivre_data = get_consolidated_grandlivre_data(uploads_folder)
    
    clients_details = {
        'creances_totales': grandlivre_data['creances_clients'],
        'nb_comptes_clients': len(grandlivre_data['comptes_details']['clients']),
        'comptes_clients': grandlivre_data['comptes_details']['clients'],
        'alertes_clients': len([c for c in grandlivre_data['comptes_details']['clients'] if c['solde'] > 5000])
    }
    print(clients_details)
    return clients_details

def get_fournisseurs_details(uploads_folder: str = 'uploads') -> Dict[str, Any]:
    """
    Récupère les détails fournisseurs pour le dashboard spécialisé
    """
    grandlivre_data = get_consolidated_grandlivre_data(uploads_folder)
    
    fournisseurs_details = {
        'dettes_totales': grandlivre_data['dettes_fournisseurs'],
        'nb_comptes_fournisseurs': len(grandlivre_data['comptes_details']['fournisseurs']),
        'comptes_fournisseurs': grandlivre_data['comptes_details']['fournisseurs'],
        'alertes_fournisseurs': len([f for f in grandlivre_data['comptes_details']['fournisseurs'] if f['solde'] > 10000])
    }
    
    return fournisseurs_details

def get_tva_details(uploads_folder: str = 'uploads') -> Dict[str, Any]:
    """
    Récupère les détails TVA pour le dashboard spécialisé
    """
    grandlivre_data = get_consolidated_grandlivre_data(uploads_folder)
    
    tva_details = {
        'tva_deductible': grandlivre_data['tva_deductible'],
        'tva_collectee': grandlivre_data['tva_collectee'],
        'tva_a_declarer': grandlivre_data['tva_collectee'] - grandlivre_data['tva_deductible'],
        'comptes_tva': grandlivre_data['comptes_details']['tva'],
        'nb_comptes_tva': len(grandlivre_data['comptes_details']['tva'])
    }
    
    return tva_details

def print_analysis_summary(uploads_folder: str = 'uploads'):
    """
    Affiche un résumé de l'analyse (pour debug/test)
    """
    data = get_consolidated_grandlivre_data(uploads_folder)
    
    print("\n------ Résumé des indicateurs comptables ------")
    print(f"✅ Total Débit : {data['total_debit']:.2f} €")
    print(f"✅ Total Crédit : {data['total_credit']:.2f} €")
    print(f"💰 Solde bancaire estimé : {data['solde_banque']:.2f} €")
    print(f"📄 Nb factures clients : {data['informations_generales']['nb_factures_clients']}")
    print(f"📄 Nb factures fournisseurs : {data['informations_generales']['nb_factures_fournisseurs']}")
    print(f"🏦 Encaissements (crédit banque) : {data['informations_generales']['encaissements']:.2f} €")
    print(f"📉 Créances clients (non encaissées) : {data['creances_clients']:.2f} €")
    print(f"📊 TVA collectée : {data['tva_collectee']:.2f} €")
    print(f"📊 TVA déductible : {data['tva_deductible']:.2f} €")
    print(f"📈 Chiffre d'affaires (706) : {data['chiffre_affaires']:.2f} €")
    print(f"📉 Charges (comptes 6xx) : {data['charges']:.2f} €")
    print(f"💼 Résultat brut : {data['resume_comptable']['resultat_brut']:.2f} €")
    print(f"🧾 TVA à déclarer : {data['resume_comptable']['tva_a_declarer']:.2f} €")

if __name__ == "__main__":
    # Test de la fonction
    print_analysis_summary()
