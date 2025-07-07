from flask import Flask, request, jsonify, render_template, send_file
import os
import subprocess
import json
import logging
from werkzeug.utils import secure_filename
from datetime import datetime
import traceback
from pipeline import UnifiedOCRProcessor, process_document_cli
from anomaly_detection_workflow import get_alerts_for_documents, extract_grandlivre_data

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

# Configuration par défaut pour la détection d'anomalies
default_config = {
    'max_date_delay_days': 3,
    'high_priority_delay_days': 1,
    'medium_priority_delay_days': 2,
    'amount_tolerance_percentage': 1.0,
    'amount_tolerance_absolute': 0.50,
    'critical_amount_threshold': 10000,
    'suspicious_amount_threshold': 1000,
    'alert_on_missing_transactions': True,
    'alert_on_duplicate_transactions': True,
    'alert_on_amount_discrepancy': True,
    'alert_on_date_discrepancy': True,
    'alert_on_unmatched_transactions': True,
    'alert_on_weekend_transactions': True,
    'alert_on_large_transactions': True,
    'monitored_bank_accounts': ["512100", "512200", "531000", "467000"],
    'critical_threshold': 80,
    'high_threshold': 60,
    'medium_threshold': 30,
    'low_threshold': 10
}

# Configuration actuelle (sera mise à jour par le dashboard)
current_config = default_config.copy()

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
    """Route pour récupérer les alertes de clôture basées sur l'analyse des fichiers JSON"""
    try:
        # Générer les alertes basées sur l'analyse des fichiers JSON des documents traités
        # Passer la configuration actuelle à la fonction
        alerts, score_risque = get_alerts_for_documents(documents_db, current_config)

        logger.info(f"Génération de {len(alerts)} alertes basées sur {len(documents_db)} documents avec config: {current_config}")
        
        return jsonify({
            'alerts': alerts,
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

@app.route('/grandlivre_data')
def get_grandlivre_data():
    """Route pour récupérer les données du grand livre pour le dashboard"""
    try:
        grandlivre_data = extract_grandlivre_data(documents_db)

        logger.info(f"Extraction des données du grand livre: {grandlivre_data['total_ecritures']} écritures")
        
        return jsonify(grandlivre_data)
        
    except Exception as e:
        logger.error(f"Erreur lors de l'extraction des données du grand livre: {str(e)}")
        logger.error(traceback.format_exc())
        
        # Retourner des données par défaut en cas d'erreur
        default_data = {
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
        return jsonify(default_data)

@app.route('/update_config', methods=['POST'])
def update_config():
    """Met à jour la configuration de détection d'anomalies"""
    global current_config
    try:
        new_config = request.get_json()
        
        # Valider et mettre à jour la configuration
        if new_config:
            # Fusionner avec la configuration par défaut pour s'assurer que tous les champs sont présents
            current_config = {**default_config, **new_config}
            
            logger.info(f"Configuration mise à jour: {current_config}")
            
            return jsonify({
                'message': 'Configuration mise à jour avec succès',
                'config': current_config
            })
        else:
            return jsonify({'error': 'Configuration invalide'}), 400
            
    except Exception as e:
        logger.error(f"Erreur mise à jour configuration: {str(e)}")
        return jsonify({'error': f'Erreur lors de la mise à jour: {str(e)}'}), 500

@app.route('/get_config', methods=['GET'])
def get_config():
    """Récupère la configuration actuelle"""
    return jsonify(current_config)

@app.route('/analysis_report', methods=['GET'])
def get_analysis_report():
    """Génère et retourne un rapport d'analyse complet"""
    try:
        # Générer les alertes avec la configuration actuelle
        alerts, score_risque = get_alerts_for_documents(documents_db, current_config)
        
        # Extraire les données du grand livre
        grandlivre_data = extract_grandlivre_data(documents_db)
        
        # Créer le rapport complet
        rapport = {
            'date_rapport': datetime.now().isoformat(),
            'configuration': current_config,
            'donnees_analysees': {
                'total_documents': len(documents_db),
                'documents_traites': len([d for d in documents_db if d['status'] == 'completed']),
                'documents_en_attente': len([d for d in documents_db if d['status'] == 'pending']),
                'documents_en_cours': len([d for d in documents_db if d['status'] == 'processing']),
                'documents_echec': len([d for d in documents_db if d['status'] == 'failed']),
                'factures': len([d for d in documents_db if d['type'] == 'facture']),
                'cheques': len([d for d in documents_db if d['type'] == 'cheque']),
                'releves': len([d for d in documents_db if d['type'] == 'releve']),
                'grandlivre': len([d for d in documents_db if d['type'] == 'grandlivre'])
            },
            'score_risque': score_risque,
            'alertes': alerts,
            'donnees_comptables': grandlivre_data,
            'statistiques_alertes': {
                'total_alertes': len(alerts),
                'alertes_haute_priorite': len([a for a in alerts if a.get('priority') == 'high']),
                'alertes_moyenne_priorite': len([a for a in alerts if a.get('priority') == 'medium']),
                'alertes_faible_priorite': len([a for a in alerts if a.get('priority') == 'low']),
                'types_alertes': {}
            }
        }
        
        # Compter les types d'alertes
        for alert in alerts:
            alert_type = alert.get('type', 'unknown')
            if alert_type not in rapport['statistiques_alertes']['types_alertes']:
                rapport['statistiques_alertes']['types_alertes'][alert_type] = 0
            rapport['statistiques_alertes']['types_alertes'][alert_type] += 1
        
        # Retourner le rapport en JSON
        response = app.response_class(
            response=json.dumps(rapport, indent=2, ensure_ascii=False),
            status=200,
            mimetype='application/json'
        )
        response.headers['Content-Disposition'] = f'attachment; filename=rapport_analyse_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        
        return response
        
    except Exception as e:
        logger.error(f"Erreur génération rapport: {str(e)}")
        return jsonify({'error': f'Erreur lors de la génération du rapport: {str(e)}'}), 500

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    """Route pour servir les fichiers uploadés (pour la visualisation des images)"""
    try:
        return send_file(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du fichier {filename}: {str(e)}")
        return jsonify({'error': 'Fichier non trouvé'}), 404

@app.route('/update_alert_status/<int:alert_id>', methods=['POST'])
def update_alert_status(alert_id):
    """Met à jour le statut d'une alerte"""
    try:
        data = request.get_json()
        new_status = data.get('status')
        comment = data.get('comment', '')
        
        if not new_status:
            return jsonify({'error': 'Statut requis'}), 400
            
        # Pour cette démo, on retourne juste un succès
        # Dans un vrai système, vous stockeriez cela en base de données
        logger.info(f"Mise à jour alerte {alert_id}: {new_status} - {comment}")
        
        return jsonify({
            'message': f'Alerte {alert_id} mise à jour avec le statut: {new_status}',
            'alert_id': alert_id,
            'status': new_status,
            'comment': comment
        })
        
    except Exception as e:
        logger.error(f"Erreur mise à jour alerte {alert_id}: {str(e)}")
        return jsonify({'error': f'Erreur lors de la mise à jour: {str(e)}'}), 500

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
        processed_data, output_path = process_document_cli(file_path, document_type)
        
        if processed_data:
            # Succès
            doc['status'] = 'completed'
            doc['processed_data'] = processed_data
            doc['output_path'] = output_path
            doc['processing_end'] = datetime.now().isoformat()
            
            logger.info(f"Document {doc_id} traité avec succès. Fichier JSON: {output_path}")
            return jsonify({
                'message': f'Document {doc["name"]} traité avec succès',
                'document': doc,
                'processed_data': processed_data
            })
        else:
            # Échec
            doc['status'] = 'failed'
            doc['error'] = 'Erreur lors du traitement OCR'
            doc['processing_end'] = datetime.now().isoformat()
            
            logger.error(f"Échec traitement document {doc_id}")
            return jsonify({'error': 'Erreur lors du traitement'}), 500
            
    except Exception as e:
        # Mettre à jour le statut en cas d'erreur
        if 'doc' in locals():
            doc['status'] = 'failed'
            doc['error'] = str(e)
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
                
                processed_data, output_path = process_document_cli(file_path, document_type)
                
                if processed_data:
                    # Succès
                    doc['status'] = 'completed'
                    doc['processed_data'] = processed_data
                    doc['output_path'] = output_path
                    doc['processing_end'] = datetime.now().isoformat()
                    
                    processed_results.append({
                        'id': doc['id'],
                        'name': doc['name'],
                        'status': 'success',
                        'data': processed_data
                    })
                    
                    logger.info(f"Document {doc['id']} traité avec succès. JSON: {output_path}")
                    
                else:
                    # Échec
                    doc['status'] = 'failed'
                    doc['error'] = 'Erreur lors du traitement OCR'
                    doc['processing_end'] = datetime.now().isoformat()
                    
                    processed_results.append({
                        'id': doc['id'],
                        'name': doc['name'],
                        'status': 'failed',
                        'error': 'Erreur lors du traitement OCR'
                    })
                    
            except Exception as e:
                # Échec individuel
                doc['status'] = 'failed'
                doc['error'] = str(e)
                doc['processing_end'] = datetime.now().isoformat()
                
                processed_results.append({
                    'id': doc['id'],
                    'name': doc['name'],
                    'status': 'failed',
                    'error': str(e)
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
    """Récupère les statistiques des documents"""
    total = len(documents_db)
    pending = len([d for d in documents_db if d['status'] == 'pending'])
    processing = len([d for d in documents_db if d['status'] == 'processing'])
    completed = len([d for d in documents_db if d['status'] == 'completed'])
    failed = len([d for d in documents_db if d['status'] == 'failed'])

    return jsonify({
        'total': total,
        'pending': pending,
        'processing': processing,
        'completed': completed,
        'failed': failed
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
