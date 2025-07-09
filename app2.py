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
from infos_gl import get_consolidated_grandlivre_data, get_dashboard_summary, get_tresorerie_details, get_clients_details, get_fournisseurs_details, get_tva_details
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
        alerts, score_risque = get_alerts_for_documents(documents_db)
        
        logger.info(f"Génération de {len(alerts)} alertes basées sur {len(documents_db)} documents")
        
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
        grandlivre_data = get_consolidated_grandlivre_data(app.config['UPLOAD_FOLDER'])
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
            'dettes_fournisseurs': 0
        }
        return jsonify(default_data)

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
    """Route pour récupérer les détails clients"""
    try:
        details = get_clients_details(app.config['UPLOAD_FOLDER'])
        return jsonify(details)
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des détails clients: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/fournisseurs_details')
def get_fournisseurs_details_route():
    """Route pour récupérer les détails fournisseurs"""
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
            # Utiliser la précision OCR calculée par le processeur
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
                    # Utiliser la précision OCR calculée par le processeur
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
    
    # Calculer la précision OCR moyenne
    completed_docs = [d for d in documents_db if d['status'] == 'completed']
    avg_accuracy = 0.0
    if completed_docs:
        total_accuracy = sum(d.get('ocr_accuracy', 0.0) for d in completed_docs)
        avg_accuracy = total_accuracy / len(completed_docs)
    
    return jsonify({
        'total': total,
        'pending': pending,
        'processing': processing,
        'completed': completed,
        'failed': failed,
        'avg_ocr_accuracy': round(avg_accuracy, 1)
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
