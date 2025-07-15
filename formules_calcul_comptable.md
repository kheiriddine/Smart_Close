# Formules de Calcul des Créances et Dettes

## 1. CRÉANCES CLIENTS (Compte 411)

### Formule de Base
```
Solde Créances Clients = Factures TTC Émises - Encaissements Reçus
```

### Détail du Calcul
```
Créances Clients = Σ(Débits compte 411) - Σ(Crédits compte 411)
```

**Si le résultat est :**
- **Positif (débiteur)** → Créances normales (clients nous doivent de l'argent)
- **Négatif (créditeur)** → Anomalie (sur-encaissements ou avances clients)

### Exemples d'Écritures Comptables

#### A. Facturation Client (Augmente les créances)
```
Débit 411 (Créances clients)           1 200,00 €
    Crédit 706 (Prestations de services)  1 000,00 €
    Crédit 44571 (TVA collectée 20%)        200,00 €
Libellé: Facture FAC2025-001 Client ABC
```

#### B. Encaissement Client (Diminue les créances)
```
Débit 512 (Banque)                     1 200,00 €
    Crédit 411 (Créances clients)      1 200,00 €
Libellé: Encaissement facture FAC2025-001 Client ABC
```

#### C. Régularisation Sur-encaissement
```
Débit 411 (Créances clients)             500,00 €
    Crédit 4191 (Clients - Avances reçues)  500,00 €
Libellé: Régularisation sur-encaissement Client ABC
```

## 2. DETTES FOURNISSEURS (Compte 401)

### Formule de Base
```
Solde Dettes Fournisseurs = Factures TTC Reçues - Paiements Effectués
```

### Détail du Calcul
```
Dettes Fournisseurs = Σ(Crédits compte 401) - Σ(Débits compte 401)
```

**Si le résultat est :**
- **Positif (créditeur)** → Dettes normales (nous devons de l'argent aux fournisseurs)
- **Négatif (débiteur)** → Anomalie (sur-paiements ou avances fournisseurs)

### Exemples d'Écritures Comptables

#### A. Facturation Fournisseur (Augmente les dettes)
```
Débit 606 (Achats)                        800,00 €
Débit 44566 (TVA déductible 20%)          160,00 €
    Crédit 401 (Dettes fournisseurs)       960,00 €
Libellé: Facture FAC-SUP-001 Fournisseur XYZ
```

#### B. Paiement Fournisseur (Diminue les dettes)
```
Débit 401 (Dettes fournisseurs)           960,00 €
    Crédit 512 (Banque)                   960,00 €
Libellé: Paiement facture FAC-SUP-001 Fournisseur XYZ
```

#### C. Régularisation Sur-paiement
```
Débit 4091 (Fournisseurs - Avances versées)  300,00 €
    Crédit 401 (Dettes fournisseurs)         300,00 €
Libellé: Régularisation sur-paiement Fournisseur XYZ
```

## 3. EXEMPLES PRATIQUES DE CALCUL

### Exemple Client ABC (Compte 411)

**Mouvements dans l'année :**
- 15/01: Facture FAC-001 → Débit 411 : 1 200 €
- 20/01: Encaissement FAC-001 → Crédit 411 : 1 200 €
- 25/01: Facture FAC-002 → Débit 411 : 800 €
- 30/01: Encaissement FAC-002 → Crédit 411 : 800 €
- 05/02: Chèque reçu (sans facture) → Crédit 411 : 500 €

**Calcul du solde :**
```
Solde 411 = (1 200 + 800) - (1 200 + 800 + 500)
Solde 411 = 2 000 - 2 500 = -500 € (créditeur)
```

**Interprétation :** Anomalie de 500 € (sur-encaissement)

**Correction nécessaire :**
```
Débit 411 (Créances clients)               500,00 €
    Crédit 4191 (Clients - Avances reçues)  500,00 €
```

**Résultat après correction :** Solde 411 = 0 € (normal)

### Exemple Fournisseur XYZ (Compte 401)

**Mouvements dans l'année :**
- 10/01: Facture reçue → Crédit 401 : 1 000 €
- 15/01: Paiement facture → Débit 401 : 1 000 €
- 20/01: Facture reçue → Crédit 401 : 600 €
- 25/01: Paiement facture → Débit 401 : 600 €
- 30/01: Paiement (sans facture) → Débit 401 : 400 €

**Calcul du solde :**
```
Solde 401 = (1 000 + 600) - (1 000 + 600 + 400)
Solde 401 = 1 600 - 2 000 = -400 € (débiteur)
```

**Interprétation :** Anomalie de 400 € (sur-paiement)

**Correction nécessaire :**
```
Débit 4091 (Fournisseurs - Avances versées)  400,00 €
    Crédit 401 (Dettes fournisseurs)         400,00 €
```

**Résultat après correction :** Solde 401 = 0 € (normal)

## 4. FORMULES POUR VOTRE GRAND LIVRE

### Pour chaque Client
```
1. Calculer : Σ Débits 411 (factures émises)
2. Calculer : Σ Crédits 411 (encaissements reçus)  
3. Solde = Débits - Crédits
4. Si solde négatif → Montant à régulariser
```

### Pour chaque Fournisseur
```
1. Calculer : Σ Crédits 401 (factures reçues)
2. Calculer : Σ Débits 401 (paiements effectués)
3. Solde = Crédits - Débits  
4. Si solde négatif → Montant à régulariser
```

## 5. ÉCRITURES DE RÉGULARISATION TYPE

### Régularisation Créances Clients
```
Débit 411 (Créances clients)                [Montant anomalie]
    Crédit 4191 (Clients - Avances reçues)   [Montant anomalie]
```

### Régularisation Dettes Fournisseurs
```
Débit 4091 (Fournisseurs - Avances versées)  [Montant anomalie]
    Crédit 401 (Dettes fournisseurs)         [Montant anomalie]
```

## 6. CONTRÔLES À EFFECTUER

### Après Régularisation
- Compte 411 : Solde débiteur ou nul
- Compte 401 : Solde créditeur ou nul
- Compte 4091 : Solde débiteur (avances fournisseurs)
- Compte 4191 : Solde créditeur (avances clients)

### Logique Finale
```
Total Créances = Solde 411 (débiteur) + Solde 4191 (créditeur)
Total Dettes = Solde 401 (créditeur) + Solde 4091 (débiteur)
```

Ces formules vous permettront de calculer précisément les montants à régulariser sans annuler tous vos soldes !