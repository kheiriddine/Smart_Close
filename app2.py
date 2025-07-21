from flask import Flask, request, jsonify, render_template, send_file
import os
import subprocess 
import json
import logging
from werkzeug.utils import secure_filename
from datetime import datetime
import traceback
from pipeline import UnifiedOCRProcessor, process_document_cli
from anomaly_detection_workflow import AnomalyDetectionWorkflow
from infos_gl import (
    get_consolidated_grandlivre_data,
    get_dashboard_summary,
    get_tresorerie_details,
    get_clients_details,
    get_fournisseurs_details,
    get_tva_details,
    find_grandlivre_json_files
)
import glob
app = Flask(__name__)

# Configuration
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf', 'xlsx', 'xls', 'csv'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Logger configuration
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Crée le dossier uploads si nécessaire
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Base de données simple en mémoire pour stocker les documents
documents_db = []
next_doc_id = 1

# Configuration par défaut pour l'analyse d'anomalies - harmonisée avec anomaly_detection_workflow.py
DEFAULT_ANOMALY_CONFIG = {
    'max_date_delay_days': 30,
    'high_priority_delay_days': 15,
    'medium_priority_delay_days': 30,
    'amount_tolerance_percentage': 0.01,
    'amount_tolerance_absolute': 0.01,
    'critical_amount_threshold': 10000,
    'suspicious_amount_threshold': 50000,
    'facture_rapprochement_days': 30,
    'cheque_rapprochement_days': 7,
    'alert_on_missing_transactions': True,
    'alert_on_duplicate_transactions': True,
    'alert_on_amount_discrepancy': True,
    'alert_on_date_discrepancy': True,
    'alert_on_unmatched_transactions': True,
    'alert_on_weekend_transactions': True,
    'alert_on_large_transactions': True,
    'alert_on_unexpected_balances': True,
    'monitored_bank_accounts': ['512200', '512100', '512300'],
    'fournisseur_accounts': ['401'],
    'charge_accounts': ['6'],
    'client_accounts': ['411'],
    'tva_accounts': ['445', '44566', '44571'],
    'critical_threshold': 80,
    'high_threshold': 60,
    'medium_threshold': 30,
    'low_threshold': 10
}

# Instance globale du workflow d'analyse d'anomalies
anomaly_workflow = AnomalyDetectionWorkflow(config=DEFAULT_ANOMALY_CONFIG)

# Liste globale des alertes supprimées pour éviter leur réapparition
suppressed_alerts = set()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_document_type_from_filename(filename):
    """Détermine le type de document basé sur le nom du fichier"""
    filename_lower = filename.lower()
    if 'facture' in filename_lower or 'invoice' in filename_lower:
        return 'facture'
    elif 'cheque' in filename_lower or 'check' in filename_lower:
        return 'cheque'
    elif 'releve' in filename_lower or 'statement' in filename_lower:
        return 'releve'
    elif 'grand' in filename_lower and 'livre' in filename_lower:
        return 'grandlivre'
    else:
        # Détection basée sur l'extension
        ext = filename.rsplit('.', 1)[1].lower()
        if ext in ['xlsx', 'xls', 'csv']:
            return 'grandlivre'
        elif ext == 'pdf':
            return 'releve'
        else:
            return 'facture'  # par défaut

@app.route('/')
def home():
    """Route pour le dashboard client principal"""
    return render_template('client_dashboard.html')

@app.route('/ocr_dashboard')
def ocr_dashboard():
    """Route pour le dashboard OCR"""
    return render_template('index.html')

@app.route('/alerts')
def get_alerts():
    """Route pour récupérer les alertes avec matching avancé"""
    try:
        # Utiliser le workflow configuré pour générer les alertes avec matching
        alerts, score_risque = anomaly_workflow.get_alerts_for_documents(documents_db)
        
        # Filtrer les alertes supprimées
        filtered_alerts = []
        for alert in alerts:
            alert_key = f"{alert.get('type', '')}_{alert.get('ref', '')}_{alert.get('montant', 0)}"
            if alert_key not in suppressed_alerts:
                filtered_alerts.append(alert)
        
        # Recalculer le score de risque avec les alertes filtrées
        score_risque = anomaly_workflow._calculate_risk_score(filtered_alerts)
        
        logger.info(f"Génération de {len(filtered_alerts)} alertes actives (sur {len(alerts)} totales) avec matching avancé basées sur {len(documents_db)} documents")
        
        return jsonify({
            'alerts': filtered_alerts,
            'score_risque': score_risque
        })
        
    except Exception as e:
        logger.error(f"Erreur lors de la génération des alertes: {str(e)}")
        logger.error(traceback.format_exc())
        
        # Retourner des alertes par défaut en cas d'erreur
        default_alerts = [
            {
                'id': 1,
                'title': 'Erreur système',
                'description': f'Erreur lors de la génération des alertes: {str(e)}',
                'priority': 'high',
                'type': 'error',
                'date': datetime.now().strftime('%Y-%m-%d'),
                'status': 'active'
            }
        ]
        return jsonify({
            'alerts': default_alerts,
            'score_risque': {'score': 0, 'niveau': 'ERREUR'}
        })

@app.route('/alerts/<int:alert_id>/adjust', methods=['POST'])
def adjust_alert(alert_id):
    """Route pour ajuster/configurer une alerte spécifique"""
    global suppressed_alerts
    
    try:
        data = request.get_json()
        action = data.get('action')  # 'validate', 'correct', 'reject'
        comment = data.get('comment', '')
        
        # Récupérer les alertes actuelles
        alerts, _ = anomaly_workflow.get_alerts_for_documents(documents_db)
        
        # Trouver l'alerte à ajuster
        alert_to_adjust = None
        for alert in alerts:
            if alert.get('id') == alert_id:
                alert_to_adjust = alert
                break
        
        if not alert_to_adjust:
            return jsonify({'error': 'Alerte non trouvée'}), 404
        
        # Traiter l'action
        if action == 'validate':
            # Valider : ne fait rien de spécial, juste marquer comme validée
            alert_to_adjust['status'] = 'validated'
            alert_to_adjust['comment'] = f"Alerte validée - Anomalie confirmée. {comment}"
            message = f'Alerte {alert_id} validée - Anomalie confirmée'
            
        elif action == 'correct':
            # Corriger : ne fait rien de spécial, juste marquer comme corrigée
            alert_to_adjust['status'] = 'corrected'
            alert_to_adjust['comment'] = f"Alerte marquée comme corrigée. {comment}"
            message = f'Alerte {alert_id} marquée comme corrigée'
            
        elif action == 'reject':
            # Rejeter : supprimer l'alerte de la liste et l'ajouter aux suppressions
            alert_key = f"{alert_to_adjust.get('type', '')}_{alert_to_adjust.get('ref', '')}_{alert_to_adjust.get('montant', 0)}"
            suppressed_alerts.add(alert_key)
            alert_to_adjust['status'] = 'rejected'
            alert_to_adjust['comment'] = f"Alerte rejetée - Fausse alerte. {comment}"
            message = f'Alerte {alert_id} rejetée et supprimée'
        
        # Marquer la date de modification
        alert_to_adjust['date_modification'] = datetime.now().isoformat()
        
        logger.info(f"Alerte {alert_id} ajustée: {action}")
        
        return jsonify({
            'message': message,
            'alert': alert_to_adjust,
            'action': action
        })
        
    except Exception as e:
        logger.error(f"Erreur lors de l'ajustement de l'alerte {alert_id}: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/alerts/reset_suppressed', methods=['POST'])
def reset_suppressed_alerts():
    """Route pour réinitialiser les alertes supprimées"""
    global suppressed_alerts
    suppressed_alerts.clear()
    logger.info("Alertes supprimées réinitialisées")
    return jsonify({'message': 'Alertes supprimées réinitialisées'})

@app.route('/alerts/matching_report')
def get_matching_report():
    """Route pour obtenir un rapport détaillé des correspondances"""
    try:
        alerts, score_risque = anomaly_workflow.get_alerts_for_documents(documents_db)
        
        # Filtrer les alertes supprimées
        filtered_alerts = []
        for alert in alerts:
            alert_key = f"{alert.get('type', '')}_{alert.get('ref', '')}_{alert.get('montant', 0)}"
            if alert_key not in suppressed_alerts:
                filtered_alerts.append(alert)
        
        # Analyser les types d'alertes pour le rapport
        matching_stats = {
            'total_alerts': len(filtered_alerts),
            'suppressed_alerts': len(suppressed_alerts),
            'missing_transactions': len([a for a in filtered_alerts if a.get('type') in ['OPERATION_MANQUANTE_GRAND_LIVRE', 'OPERATION_MANQUANTE_RELEVE', 'TRANSACTION_MANQUANTE']]),
            'duplicate_transactions': len([a for a in filtered_alerts if 'DOUBLON' in a.get('type', '')]),
            'amount_discrepancies': len([a for a in filtered_alerts if a.get('type') == 'ECART_MONTANT']),
            'date_discrepancies': len([a for a in filtered_alerts if a.get('type') == 'SEQUENCE_ILLOGIQUE']),
            'weekend_transactions': len([a for a in filtered_alerts if a.get('type') in ['JOUR_NON_OUVRABLE', 'TRANSACTION_JOUR_NON_OUVRABLE']]),
            'large_transactions': len([a for a in filtered_alerts if a.get('type') in ['ARRONDI_SUSPECT', 'TRANSACTION_MONTANT_ELEVE']]),
            'missing_invoices': len([a for a in filtered_alerts if a.get('type') == 'FACTURE_MANQUANTE_GL']),
            'missing_checks': len([a for a in filtered_alerts if a.get('type') == 'CHEQUE_MANQUANT_GL'])
        }
        
        # Statistiques par document
        doc_stats = {}
        for doc in documents_db:
            if doc['status'] == 'completed':
                doc_alerts = [a for a in filtered_alerts if a.get('document_id') == doc['id']]
                doc_stats[doc['name']] = {
                    'type': doc['type'],
                    'alerts_count': len(doc_alerts),
                    'high_priority': len([a for a in doc_alerts if a.get('priority') == 'high']),
                    'medium_priority': len([a for a in doc_alerts if a.get('priority') == 'medium']),
                    'low_priority': len([a for a in doc_alerts if a.get('priority') == 'low'])
                }
        
        # Recalculer le score de risque avec les alertes filtrées
        score_risque = anomaly_workflow._calculate_risk_score(filtered_alerts)
        
        return jsonify({
            'matching_stats': matching_stats,
            'document_stats': doc_stats,
            'score_risque': score_risque,
        })
        
    except Exception as e:
        logger.error(f"Erreur lors de la génération du rapport de matching: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/config/anomaly', methods=['GET'])
def get_anomaly_config():
    """Route pour récupérer la configuration actuelle de l'analyse d'anomalies"""
    try:
        return jsonify({
            'config': anomaly_workflow.config,
            'message': 'Configuration récupérée avec succès'
        })
    except Exception as e:
        logger.error(f"Erreur lors de la récupération de la configuration: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/config/anomaly', methods=['POST'])
def update_anomaly_config():
    """Route pour mettre à jour la configuration de l'analyse d'anomalies"""
    try:
        global anomaly_workflow
        
        new_config = request.get_json()
        if not new_config:
            return jsonify({'error': 'Configuration manquante'}), 400
        
        # Valider et fusionner avec la configuration par défaut
        updated_config = DEFAULT_ANOMALY_CONFIG.copy()
        updated_config.update(new_config)
        
        # Créer une nouvelle instance du workflow avec la nouvelle configuration
        anomaly_workflow = AnomalyDetectionWorkflow(config=updated_config)
        
        logger.info("Configuration d'analyse d'anomalies mise à jour avec matching avancé")
        
        return jsonify({
            'message': 'Configuration mise à jour avec succès',
            'config': updated_config
        })
        
    except Exception as e:
        logger.error(f"Erreur lors de la mise à jour de la configuration: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/config/anomaly/reset', methods=['POST'])
def reset_anomaly_config():
    """Route pour réinitialiser la configuration aux valeurs par défaut"""
    try:
        global anomaly_workflow
        
        # Réinitialiser avec la configuration par défaut
        anomaly_workflow = AnomalyDetectionWorkflow(config=DEFAULT_ANOMALY_CONFIG.copy())
        
        logger.info("Configuration d'analyse d'anomalies réinitialisée")
        
        return jsonify({
            'message': 'Configuration réinitialisée aux valeurs par défaut',
            'config': DEFAULT_ANOMALY_CONFIG
        })
        
    except Exception as e:
        logger.error(f"Erreur lors de la réinitialisation de la configuration: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/grandlivre_data')
def get_grandlivre_data():
    """Route pour récupérer les données du grand livre pour le dashboard"""
    grandlivre_data = {}
    try:
        consolidated_data = get_consolidated_grandlivre_data(app.config['UPLOAD_FOLDER'])
            # Fusionner les données si possible
        if consolidated_data:
            grandlivre_data.update(consolidated_data)
    except Exception as e:
        logger.warning(f"Impossible d'obtenir les données consolidées: {str(e)}")
        
    logger.info(f"Extraction des données du grand livre")
        
    return jsonify(grandlivre_data)
        
    

@app.route('/dashboard_summary')
def get_dashboard_summary_route():
    """Route pour récupérer le résumé du dashboard"""
    try:
        summary = get_dashboard_summary(app.config['UPLOAD_FOLDER'])
        return jsonify(summary)
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du résumé: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/tresorerie_details')
def get_tresorerie_details_route():
    """Route pour récupérer les détails de trésorerie"""
    try:
        details = get_tresorerie_details(app.config['UPLOAD_FOLDER'])
        return jsonify(details)
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des détails trésorerie: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/clients_details')
def get_clients_details_route():
    """Route pour récupérer les détails clients avec créances calculées"""
    try:
        details = get_clients_details(app.config['UPLOAD_FOLDER'])
        return jsonify(details)
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des détails clients: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/fournisseurs_details')
def get_fournisseurs_details_route():
    """Route pour récupérer les détails fournisseurs avec dettes calculées"""
    try:
        details = get_fournisseurs_details(app.config['UPLOAD_FOLDER'])
        return jsonify(details)
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des détails fournisseurs: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/tva_details')
def get_tva_details_route():
    """Route pour récupérer les détails TVA"""
    try:
        details = get_tva_details(app.config['UPLOAD_FOLDER'])
        return jsonify(details)
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des détails TVA: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    """Route pour servir les fichiers uploadés (pour la visualisation des images)"""
    try:
        return send_file(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du fichier {filename}: {str(e)}")
        return jsonify({'error': 'Fichier non trouvé'}), 404

@app.route('/upload', methods=['POST'])
def upload_files():
    """Upload multiple files"""
    global next_doc_id
    
    try:
        if 'files' not in request.files:
            return jsonify({'error': 'Aucun fichier fourni'}), 400
        
        files = request.files.getlist('files')
        uploaded_docs = []
        
        for file in files:
            if file and file.filename and allowed_file(file.filename):
                # Sécuriser le nom de fichier
                filename = secure_filename(file.filename)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{timestamp}_{filename}"
                
                # Sauvegarder le fichier
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)
                
                # Déterminer le type de document
                doc_type = get_document_type_from_filename(file.filename)
                
                # Ajouter à la base de données
                doc = {
                    'id': next_doc_id,
                    'name': file.filename,
                    'filename': filename,
                    'type': doc_type,
                    'status': 'pending',
                    'upload_date': datetime.now().isoformat(),
                    'file_path': file_path,
                    'size': os.path.getsize(file_path),
                    'processed_data': None,
                    'ocr_accuracy': 0.0,
                    'error': None
                }
                
                documents_db.append(doc)
                uploaded_docs.append(doc)
                next_doc_id += 1
                
                logger.info(f"Fichier uploadé: {filename}, Type: {doc_type}")
        
        return jsonify({
            'message': f'{len(uploaded_docs)} fichier(s) uploadé(s) avec succès',
            'documents': uploaded_docs
        })
        
    except Exception as e:
        logger.error(f"Erreur upload: {str(e)}")
        return jsonify({'error': f'Erreur lors de l\'upload: {str(e)}'}), 500

@app.route('/documents', methods=['GET'])
def get_documents():
    """Récupère la liste de tous les documents"""
    return jsonify(documents_db)

@app.route('/documents/<int:doc_id>', methods=['GET'])
def get_document(doc_id):
    """Récupère un document spécifique"""
    doc = next((d for d in documents_db if d['id'] == doc_id), None)
    if not doc:
        return jsonify({'error': 'Document non trouvé'}), 404
    return jsonify(doc)

@app.route('/process_document/<int:doc_id>', methods=['POST'])
def process_single_document(doc_id):
    """Traite un document individuel"""
    try:
        # Trouver le document
        doc = next((d for d in documents_db if d['id'] == doc_id), None)
        if not doc:
            return jsonify({'error': 'Document non trouvé'}), 404
        
        if doc['status'] != 'pending':
            return jsonify({'error': 'Document déjà traité ou en cours de traitement'}), 400
        
        # Mettre à jour le statut
        doc['status'] = 'processing'
        doc['processing_start'] = datetime.now().isoformat()
        
        logger.info(f"Début traitement document {doc_id}: {doc['name']}")
        
        # Traiter le document avec pipeline.py
        file_path = doc['file_path']
        document_type = doc['type']
        
        # Utiliser la fonction process_document_cli du pipeline
        processed_data, output_path, ocr_accuracy = process_document_cli(file_path, document_type)
        
        if processed_data:
            # Succès
            doc['status'] = 'completed'
            doc['processed_data'] = processed_data
            doc['output_path'] = output_path
            doc['ocr_accuracy'] = ocr_accuracy
            doc['processing_end'] = datetime.now().isoformat()
            
            logger.info(f"Document {doc_id} traité avec succès. Fichier JSON: {output_path}")
            logger.info(f"Précision OCR: {doc['ocr_accuracy']:.1f}%")
            return jsonify({
                'message': f'Document {doc["name"]} traité avec succès',
                'document': doc,
                'processed_data': processed_data
            })
        else:
            # Échec
            doc['status'] = 'failed'
            doc['error'] = 'Erreur lors du traitement OCR'
            doc['ocr_accuracy'] = 0.0
            doc['processing_end'] = datetime.now().isoformat()
            
            logger.error(f"Échec traitement document {doc_id}")
            return jsonify({'error': 'Erreur lors du traitement'}), 500
            
    except Exception as e:
        # Mettre à jour le statut en cas d'erreur
        if 'doc' in locals():
            doc['status'] = 'failed'
            doc['error'] = str(e)
            doc['ocr_accuracy'] = 0.0
            doc['processing_end'] = datetime.now().isoformat()
        
        logger.error(f"Erreur traitement document {doc_id}: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': f'Erreur lors du traitement: {str(e)}'}), 500

@app.route('/process_documents', methods=['POST'])
def process_documents():
    """Traite plusieurs documents (tous les documents en attente)"""
    try:
        # Trouver tous les documents en attente
        pending_docs = [d for d in documents_db if d['status'] == 'pending']
        
        if not pending_docs:
            return jsonify({'message': 'Aucun document en attente', 'processed': []})
        
        processed_results = []
        
        for doc in pending_docs:
            try:
                # Mettre à jour le statut
                doc['status'] = 'processing'
                doc['processing_start'] = datetime.now().isoformat()
                
                logger.info(f"Traitement document {doc['id']}: {doc['name']}")
                
                # Traiter le document
                file_path = doc['file_path']
                document_type = doc['type']
                
                processed_data, output_path, ocr_accuracy = process_document_cli(file_path, document_type)
                
                if processed_data:
                    # Succès
                    doc['status'] = 'completed'
                    doc['processed_data'] = processed_data
                    doc['output_path'] = output_path
                    doc['ocr_accuracy'] = ocr_accuracy
                    doc['processing_end'] = datetime.now().isoformat()
                    
                    processed_results.append({
                        'id': doc['id'],
                        'name': doc['name'],
                        'status': 'success',
                        'data': processed_data,
                        'ocr_accuracy': doc['ocr_accuracy']
                    })
                    
                    logger.info(f"Document {doc['id']} traité avec succès. JSON: {output_path}")
                    logger.info(f"Précision OCR: {doc['ocr_accuracy']:.1f}%")
                    
                else:
                    # Échec
                    doc['status'] = 'failed'
                    doc['error'] = 'Erreur lors du traitement OCR'
                    doc['ocr_accuracy'] = 0.0
                    doc['processing_end'] = datetime.now().isoformat()
                    
                    processed_results.append({
                        'id': doc['id'],
                        'name': doc['name'],
                        'status': 'failed',
                        'error': 'Erreur lors du traitement OCR',
                        'ocr_accuracy': 0.0
                    })
                    
            except Exception as e:
                # Échec individuel
                doc['status'] = 'failed'
                doc['error'] = str(e)
                doc['ocr_accuracy'] = 0.0
                doc['processing_end'] = datetime.now().isoformat()
                
                processed_results.append({
                    'id': doc['id'],
                    'name': doc['name'],
                    'status': 'failed',
                    'error': str(e),
                    'ocr_accuracy': 0.0
                })
                
                logger.error(f"Erreur traitement document {doc['id']}: {str(e)}")
        
        success_count = len([r for r in processed_results if r['status'] == 'success'])
        
        logger.info(f"Traitement batch terminé: {success_count}/{len(processed_results)} documents traités avec succès")
        
        return jsonify({
            'message': f'{success_count}/{len(processed_results)} documents traités avec succès',
            'processed': processed_results
        })
        
    except Exception as e:
        logger.error(f"Erreur traitement batch: {str(e)}")
        return jsonify({'error': f'Erreur lors du traitement: {str(e)}'}), 500

@app.route('/download_json/<int:doc_id>', methods=['GET'])
def download_json(doc_id):
    """Télécharge le fichier JSON d'un document traité"""
    try:
        doc = next((d for d in documents_db if d['id'] == doc_id), None)
        if not doc:
            return jsonify({'error': 'Document non trouvé'}), 404
        
        if doc['status'] != 'completed' or not doc.get('output_path'):
            return jsonify({'error': 'Document non traité ou fichier JSON non disponible'}), 400
        
        output_path = doc['output_path']
        if not os.path.exists(output_path):
            return jsonify({'error': 'Fichier JSON non trouvé'}), 404
        
        return send_file(output_path, as_attachment=True, 
                        download_name=f"Output_{doc['name']}.json")
        
    except Exception as e:
        logger.error(f"Erreur téléchargement JSON {doc_id}: {str(e)}")
        return jsonify({'error': f'Erreur lors du téléchargement: {str(e)}'}), 500

@app.route('/save_json/<int:doc_id>', methods=['POST'])
def save_json(doc_id):
    """Sauvegarde le contenu JSON modifié d'un document"""
    try:
        doc = next((d for d in documents_db if d['id'] == doc_id), None)
        if not doc:
            return jsonify({'error': 'Document non trouvé'}), 404

        if doc['status'] != 'completed':
            return jsonify({'error': 'Document non traité'}), 400

        data = request.get_json()
        if not data or 'json_content' not in data:
            return jsonify({'error': 'Contenu JSON manquant'}), 400

        json_content = data['json_content']

        # Valider le JSON
        try:
            parsed_json = json.loads(json_content)
        except json.JSONDecodeError as e:
            return jsonify({'error': f'JSON invalide: {str(e)}'}), 400

        # Écraser le fichier existant
        if doc.get('output_path') and os.path.exists(doc['output_path']):
            json_file_path = doc['output_path']
        else:
            # Créer un nouveau fichier JSON dans uploads
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            json_filename = f"edited_{timestamp}_{doc['name']}.json"
            json_file_path = os.path.join(app.config['UPLOAD_FOLDER'], json_filename)
            doc['output_path'] = json_file_path

        with open(json_file_path, 'w', encoding='utf-8') as f:
            f.write(json_content)

        # Mettre à jour les données du document
        doc['processed_data'] = parsed_json
        doc['last_modified'] = datetime.now().isoformat()

        # Forcer le recalcul des alertes (optionnel, mais recommandé)
        # anomaly_workflow.get_alerts_for_documents(documents_db)

        return jsonify({
            'message': f"JSON sauvegardé avec succès pour {doc['name']}",
            'file_path': json_file_path
        })
    except Exception as e:
        return jsonify({'error': f'Erreur lors de la sauvegarde: {str(e)}'}), 500

@app.route('/delete_document/<int:doc_id>', methods=['DELETE'])
def delete_document(doc_id):
    """Supprime un document"""
    try:
        doc = next((d for d in documents_db if d['id'] == doc_id), None)
        if not doc:
            return jsonify({'error': 'Document non trouvé'}), 404
        
        # Supprimer les fichiers
        if os.path.exists(doc['file_path']):
            os.remove(doc['file_path'])
        
        if doc.get('output_path') and os.path.exists(doc['output_path']):
            os.remove(doc['output_path'])
        
        # Supprimer de la base de données
        documents_db.remove(doc)
        
        logger.info(f"Document {doc_id} supprimé")
        return jsonify({'message': f'Document {doc["name"]} supprimé avec succès'})
        
    except Exception as e:
        logger.error(f"Erreur suppression document {doc_id}: {str(e)}")
        return jsonify({'error': f'Erreur lors de la suppression: {str(e)}'}), 500

@app.route('/stats', methods=['GET'])
def get_stats():
    """Récupère les statistiques des documents avec informations de matching"""
    total = len(documents_db)
    pending = len([d for d in documents_db if d['status'] == 'pending'])
    processing = len([d for d in documents_db if d['status'] == 'processing'])
    completed = len([d for d in documents_db if d['status'] == 'completed'])
    failed = len([d for d in documents_db if d['status'] == 'failed'])
    
    # Calculer la précision OCR moyenne avec les vraies valeurs
    completed_docs = [d for d in documents_db if d['status'] == 'completed']
    avg_accuracy = 0.0
    if completed_docs:
        total_accuracy = sum(d.get('ocr_accuracy', 0.0) for d in completed_docs)
        avg_accuracy = total_accuracy / len(completed_docs)
    
    # Statistiques par type de document
    doc_types = {}
    for doc in documents_db:
        doc_type = doc['type']
        if doc_type not in doc_types:
            doc_types[doc_type] = {'total': 0, 'completed': 0, 'failed': 0}
        doc_types[doc_type]['total'] += 1
        if doc['status'] == 'completed':
            doc_types[doc_type]['completed'] += 1
        elif doc['status'] == 'failed':
            doc_types[doc_type]['failed'] += 1
    
    # Obtenir les statistiques de matching
    matching_stats = {}
    try:
        alerts, score_risque = anomaly_workflow.get_alerts_for_documents(documents_db)
        
        # Filtrer les alertes supprimées
        filtered_alerts = []
        for alert in alerts:
            alert_key = f"{alert.get('type', '')}_{alert.get('ref', '')}_{alert.get('montant', 0)}"
            if alert_key not in suppressed_alerts:
                filtered_alerts.append(alert)
        
        # Recalculer le score de risque avec les alertes filtrées
        score_risque = anomaly_workflow._calculate_risk_score(filtered_alerts)
        
        matching_stats = {
            'total_alerts': len(filtered_alerts),
            'suppressed_alerts': len(suppressed_alerts),
            'risk_score': score_risque['score'],
            'risk_level': score_risque['niveau'],
            'high_priority_alerts': len([a for a in filtered_alerts if a.get('priority') == 'high']),
            'medium_priority_alerts': len([a for a in filtered_alerts if a.get('priority') == 'medium']),
            'low_priority_alerts': len([a for a in filtered_alerts if a.get('priority') == 'low'])
        }
    except Exception as e:
        logger.error(f"Erreur calcul stats matching: {str(e)}")
        matching_stats = {'error': str(e)}
    
    return jsonify({
        'total': total,
        'pending': pending,
        'processing': processing,
        'completed': completed,
        'failed': failed,
        'avg_ocr_accuracy': round(avg_accuracy, 1),
        'doc_types': doc_types,
        'matching_stats': matching_stats
    })

@app.route('/correction/<int:alert_id>')
def correction_fenetre(alert_id):
    """Affiche la fenêtre de correction pour une alerte spécifique."""
    return render_template('fenetre.html', alert_id=alert_id)

@app.route('/correction_jno/<int:alert_id>')
def correction_jno_fenetre(alert_id):
    """Affiche la fenêtre de correction pour une transaction sur jour non ouvrable."""
    return render_template('fenetre_jno.html', alert_id=alert_id)

@app.route('/correction_ecart/<int:alert_id>')
def correction_ecart_fenetre(alert_id):
    """Affiche la fenêtre de correction pour un écart de montant."""
    return render_template('fenetre_ecart.html', alert_id=alert_id)

@app.route('/invoice_data/<invoice_ref>')
def get_invoice_data(invoice_ref):
    """Trouve les données d'une facture à partir de sa référence (Numéro Facture)."""
    for doc in documents_db:
        if doc.get('type') == 'facture' and doc.get('status') == 'completed' and doc.get('processed_data'):
            processed_data = doc.get('processed_data', {})
            info_payment = processed_data.get('info payment', {})
            numero_facture = info_payment.get('Numéro Facture') or processed_data.get('Numéro Facture')
            if numero_facture and numero_facture.strip() == invoice_ref.strip():
                return jsonify({
                    'document_id': doc['id'],
                    'file_name': doc['name'],
                    'total_ttc': info_payment.get('Total TTC') or processed_data.get('Total TTC'),
                    'json_content': processed_data
                })
    return jsonify({'error': 'Facture non trouvée'}), 404

@app.route('/check_data/<check_ref>')
def get_check_data(check_ref):
    """Trouve les données d'un chèque à partir de son numéro."""
    for doc in documents_db:
        if doc.get('type') == 'cheque' and doc.get('status') == 'completed' and doc.get('processed_data'):
            processed_data = doc.get('processed_data', {})
            check_number = processed_data.get('Numéro de Chèque')
            if check_number and check_number.strip() == check_ref.strip():
                return jsonify({
                    'document_id': doc['id'],
                    'file_name': doc['name'],
                    'montant_cheque': processed_data.get('Montant du Chèque'),
                    'json_content': processed_data
                })
    return jsonify({'error': 'Chèque non trouvé'}), 404

@app.route('/latest_doc_json/<doc_type>')
def get_latest_doc_json(doc_type):
    """Renvoie le contenu JSON du document le plus récent du type spécifié (grandlivre ou releve)."""
    doc_id = find_latest_doc_id_by_type(doc_type)
    if not doc_id:
        return jsonify({'error': f'Aucun document de type {doc_type} trouvé'}), 404
    
    doc = next((d for d in documents_db if d['id'] == doc_id), None)
    if not doc or not doc.get('output_path') or not os.path.exists(doc['output_path']):
        return jsonify({'error': 'Fichier JSON non trouvé pour le document le plus récent'}), 404
    
    with open(doc['output_path'], 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    return jsonify({
        'document_id': doc_id,
        'json_content': data
    })
    
def find_latest_doc_id_by_type(doc_type):
    # doc_type: 'grandlivre' ou 'releve'
    pattern = 'Grand_livre_comptable' if doc_type == 'grandlivre' else 'Generateur_de_Releve_Bancaire_BNP_Paribas'
    files = sorted(
        glob.glob(os.path.join(UPLOAD_FOLDER, f'Output_*_{pattern}.json')),
        key=os.path.getmtime,
        reverse=True
    )
    if not files:
        return None
    latest_file = os.path.basename(files[0])
    for d in documents_db:
        if d.get('output_path') and latest_file in d['output_path']:
            return d['id']
    return None

@app.route('/alert_data/<int:alert_id>')
def get_alert_data(alert_id):
    alert = next((a for a in getattr(app, 'alerts', []) if a['id'] == alert_id), None)
    if not alert:
        try:
            alerts, _ = anomaly_workflow.get_alerts_for_documents(documents_db)
            alert = next((a for a in alerts if a['id'] == alert_id), None)
        except Exception as e:
            return jsonify({'error': str(e)}), 404
    if not alert:
        return jsonify({'error': 'Alerte non trouvée'}), 404
    # S'assurer que document_id et type sont présents
    if 'document_id' not in alert or not alert.get('document_id'):
        doc = None
        ref = alert.get('ref')
        alert_type = alert.get('type', '').lower()
        for d in documents_db:
            if d.get('status') == 'completed':
                if ref and ref in str(d.get('name', '')):
                    doc = d
                    break
                if alert_type and alert_type in str(d.get('type', '')).lower():
                    doc = d
        if doc:
            alert['document_id'] = doc['id']
            alert['doc_type'] = doc['type']
        # Fallback : prendre le plus récent GL ou RL si rien trouvé
        if not alert.get('document_id'):
            if 'grandlivre' in alert_type or 'gl' in alert.get('source', '').lower():
                doc_id = find_latest_doc_id_by_type('grandlivre')
                if doc_id:
                    alert['document_id'] = doc_id
            elif 'releve' in alert_type or 'rl' in alert.get('source', '').lower():
                doc_id = find_latest_doc_id_by_type('releve')
                if doc_id:
                    alert['document_id'] = doc_id
    return jsonify(alert)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)

