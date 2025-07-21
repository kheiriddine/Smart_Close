# Smart Close - Plateforme de Rapprochement Comptable et Détection d'Anomalies

## 🚀 Démarrage rapide

### Prérequis
- Python 3.8+
- `pip install -r requirements.txt`
- (Optionnel) Clé API TogetherAI pour l'OCR avancé

### Installation et lancement
```bash
pip install -r requirements.txt
python app2.py
```
L'application sera accessible sur [http://localhost:5000](http://localhost:5000)

---

## 📝 Workflow général
1. **Upload de documents** : Factures, chèques, relevés bancaires, grands livres (formats PDF, image, Excel, etc.)
2. **OCR automatique** : Extraction des données via EasyOCR, PaddleOCR, ou TogetherAI (LLM OCR)
3. **Détection d'anomalies** : Analyse croisée des écritures, détection des incohérences, génération d'alertes
4. **Correction assistée** : Fenêtres dédiées pour corriger chaque type d'anomalie, avec pré-remplissage intelligent
5. **Sauvegarde** : Les corrections sont enregistrées dans les fichiers JSON originaux (pas dans le GL/RL sauf action dédiée)

---

## 🔎 Types d'anomalies détectées & méthodologie de rapprochement

### 1. **Facture non rapprochée**
- **Détection** : Facture présente dans les comptes métier (401/411/6xxx) mais absente du compte bancaire (512xxx)
- **Méthodologie** :
  - Recherche de la référence facture dans le GL et le RL
  - Vérification du paiement/encaissement
  - Suggestion d'ajout d'une écriture de règlement dans le GL

### 2. **Chèque non comptabilisé**
- **Détection** : Chèque détecté dans le RL mais aucune écriture correspondante dans le GL
- **Méthodologie** :
  - Recherche du numéro de chèque dans le GL
  - Suggestion d'ajout d'une écriture d'encaissement (débit 512xxx, crédit 411xxx ou autre)

### 3. **Chèque émis non encaissé**
- **Détection** : Chèque émis (comptes de sortie) mais non retrouvé dans le compte bancaire
- **Méthodologie** :
  - Vérification de la présence du chèque dans le GL (émission) et RL (encaissement)
  - Suggestion d'ajout d'une écriture d'encaissement dans le GL

### 4. **Chèque encaissé non émis**
- **Détection** : Chèque trouvé dans le RL mais pas d'émission dans le GL
- **Méthodologie** :
  - Suggestion d'ajout d'une écriture d'origine (débit 411xxx, crédit 512xxx)

### 5. **Chèque incohérent**
- **Détection** : Montant différent entre émission et encaissement
- **Méthodologie** :
  - Suggestion d'ajout d'une écriture d'écart (compte 658xxx ou 758xxx)

### 6. **Écart de montant**
- **Détection** : Différence entre le montant d'une opération dans le GL et le RL
- **Méthodologie** :
  - Affichage comparatif, correction manuelle possible

### 7. **Numéro manquant (chèque/facture)**
- **Détection** : Numéro de chèque ou de facture absent dans le document OCR
- **Méthodologie** :
  - Fenêtre dédiée pour saisir le numéro manquant et mettre à jour le fichier OCR

### 8. **Transaction sur jour non ouvrable**
- **Détection** : Opération détectée un week-end ou jour férié
- **Méthodologie** :
  - Suggestion de correction de la date

---

## ⚙️ Configuration des alertes
- Les seuils et règles sont définis dans `DEFAULT_ANOMALY_CONFIG` (voir `app2.py` ou `uploads/anomaly_config.json`)
- Exemples de paramètres :
  - `critical_threshold`, `high_threshold`, `medium_threshold`, `low_threshold`
  - `amount_tolerance_percentage`, `amount_tolerance_absolute`
  - `alert_on_missing_transactions`, `alert_on_duplicate_transactions`, etc.
- **Personnalisation** : Modifiez ces valeurs pour adapter la sensibilité du système à vos besoins.

---

## 🤖 OCR utilisés

### 1. **EasyOCR**
- [Site officiel](https://github.com/JaidedAI/EasyOCR)
- [Paper](https://arxiv.org/abs/2005.03983)
- ![EasyOCR logo](https://raw.githubusercontent.com/JaidedAI/EasyOCR/master/logo.png)
- Utilisé pour les factures (images)

### 2. **PaddleOCR**
- [Site officiel](https://github.com/PaddlePaddle/PaddleOCR)
- [Paper](https://arxiv.org/abs/2009.09941)
- ![PaddleOCR logo](https://user-images.githubusercontent.com/21303438/88454717-2b2e7d80-cea6-11ea-8c0b-6b7b7b7b7b7b.png)
- Utilisé pour les chèques (images)

### 3. **TogetherAI (LLM OCR)**
- [Site officiel](https://www.together.ai/)
- [Paper](https://arxiv.org/abs/2305.15023)
- Utilisé pour l'extraction intelligente et la correction contextuelle

---

## 🪄 Utilisation des fenêtres de correction
- Chaque type d'anomalie ouvre une fenêtre dédiée, au design harmonisé, avec pré-remplissage intelligent.
- Les corrections sont enregistrées dans le fichier JSON du document original (facture ou chèque) ou dans le GL/RL selon le contexte.
- Les dates sont toujours au format **JJ/MM/AAAA**.
- Les guides contextuels vous assistent pour chaque cas métier.

---

## 📚 Méthodologie de rapprochement (résumé)
- **Rapprochement GL/RL** :
  - Recherche de références croisées (numéro de facture, chèque, etc.)
  - Vérification des montants, dates, comptes
  - Application de règles métier pour chaque type d'anomalie
- **Correction** :
  - L'utilisateur est guidé pour ajouter, corriger ou compléter les écritures nécessaires

---

## 💡 Conseils
- Toujours vérifier les montants et les dates avant d'enregistrer une correction
- Utiliser les guides affichés dans chaque fenêtre pour éviter les erreurs de saisie
- Adapter la configuration des alertes à la réalité de votre entreprise

---

## 📞 Support
Pour toute question ou suggestion, contactez l'équipe Smart Close.
