# Clarification : Factures vs Chèques

## Ce ne sont PAS deux types de documents équivalents !

### 📄 **FACTURE** = Document de Vente
- **Émise par VOUS** vers le client
- **Demande de paiement** pour des services/produits
- **Crée une créance** (le client vous doit de l'argent)
- **Écriture :** Débit 411 (augmente les créances)

### 💰 **CHÈQUE** = Moyen de Paiement  
- **Reçu du CLIENT** 
- **Règlement** d'une ou plusieurs factures
- **Réduit la créance** (le client vous paie)
- **Écriture :** Crédit 411 (diminue les créances)

## Le Cycle Normal

```
1. VOUS émettez une facture → Client vous doit 1000 €
2. CLIENT envoie un chèque → Client vous paie 1000 €
3. Créance = 0 € (équilibrée)
```

## Que Signifie "Chèque Sans Facture" ?

### Situation Normale
```
✅ 31/01/2025 - Facture FAC2025010171 BNP : +15 792,83 €
✅ 28/02/2025 - Chèque pour FAC2025010171 : -15 792,83 €
→ Facture payée, créance = 0 €
```

### Situation Anormale  
```
❌ 02/10/2025 - Chèque N°2685339 BNP : -22 805,69 €
→ Aucune facture correspondante visible !
```

**"Sans facture" signifie :** Vous avez reçu un chèque de 22 805,69 € de BNP Paribas, mais vous ne trouvez **aucune facture** de ce montant que vous auriez émise à BNP.

## Causes Possibles du "Chèque Sans Facture"

### 1. **Erreur de Comptabilisation**
- Le chèque appartient à un autre client
- Erreur de saisie du montant ou du client

### 2. **Facture Oubliée** 
- Vous avez fait le travail mais oublié d'émettre la facture
- La facture existe mais n'est pas comptabilisée

### 3. **Avance Client Réelle**
- Le client paie à l'avance pour des futurs services
- Vous devrez facturer plus tard

### 4. **Regroupement de Paiements**
- Le chèque paie plusieurs petites factures
- Difficile à identifier individuellement

## Analyse de Votre Grand Livre

### Exemple BNP Paribas
```
Dans vos écritures :
✅ Facture FAC2025010171 : 15 792,83 € (31/01/2025)
✅ Encaissement de cette facture : 15 792,83 € (28/02/2025)
❌ Chèque N°2685339 : 22 805,69 € (02/10/2025) → ORPHELIN !
```

**Question à se poser :** 
Avez-vous émis une facture de 22 805,69 € à BNP Paribas qui ne serait pas dans ce grand livre ?

## Ce Qu'il Faut Vérifier

### 1. **Rechercher les Factures Manquantes**
- Vérifier vos archives de facturation
- Contrôler s'il y a des factures non comptabilisées

### 2. **Vérifier les Montants**
- Le chèque pourrait correspondre à plusieurs factures
- Additionner les factures pour retrouver le total

### 3. **Contacter le Client**
- Demander à BNP Paribas à quoi correspond ce paiement
- Obtenir leur référence/justification

## Solutions Selon le Cas

### Si Facture Retrouvée
```
Passer la facture manquante :
Débit 411 (Créances clients)     22 805,69 €
    Crédit 706 (Prestations)     19 004,74 €
    Crédit 44571 (TVA 20%)        3 800,95 €
```

### Si Vraie Avance Client
```
Régulariser en avance :
Débit 411 (Créances clients)          22 805,69 €
    Crédit 4191 (Avances clients)     22 805,69 €
```

### Si Erreur de Client
```
Corriger l'imputation :
Débit 411 (Bon client)               22 805,69 €
    Crédit 411 (Mauvais client)      22 805,69 €
```

## Résumé

**"Chèque sans facture"** = Vous avez reçu de l'argent d'un client, mais vous ne savez pas pourquoi !

C'est pour cela que le solde devient négatif : vous avez encaissé plus que ce que vous avez facturé à ce client.

La solution dépend de la raison : facture oubliée, avance client, ou erreur de saisie.

Voulez-vous qu'on analyse quelques chèques spécifiques pour identifier leur origine ?