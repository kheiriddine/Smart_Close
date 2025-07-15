# Calcul des Créances avec Factures ET Chèques

## Principe de Base

Quand vous avez des **factures ET des chèques** pour un même client, la créance se calcule ainsi :

```
Créance Réelle = Factures Émises - Encaissements Correspondant aux Factures
```

## Méthode de Rapprochement

### Étape 1 : Lister par Client
1. **TOUTES les factures émises** (débits 411)
2. **TOUS les encaissements reçus** (crédits 411)

### Étape 2 : Faire le Rapprochement
3. **Identifier les encaissements liés aux factures**
4. **Identifier les encaissements "orphelins"** (sans facture)

## Exemples Concrets

### Cas 1 : Client avec Factures et Chèques Correspondants

**Client : InfoVista Ltd**
```
✅ 31/01/2025 - Facture FAC2025010102 : +4 445,71 € (Débit 411)
✅ 28/02/2025 - Encaissement FAC2025010102 : -4 445,71 € (Crédit 411)
```

**Calcul :**
```
Créance = 4 445,71 - 4 445,71 = 0 €
```
**Résultat :** Pas de créance (facture payée) ✅

---

### Cas 2 : Client avec Factures Partiellement Payées

**Client : NexusMetrics Solutions**
```
✅ 31/01/2025 - Facture FAC2025010104 : +10 965,54 € (Débit 411)
✅ 28/02/2025 - Encaissement partiel : -8 000,00 € (Crédit 411)
```

**Calcul :**
```
Créance = 10 965,54 - 8 000,00 = +2 965,54 €
```
**Résultat :** Créance de 2 965,54 € (normal) ✅

---

### Cas 3 : Client avec Factures + Chèque Orphelin

**Client : BNP Paribas**
```
✅ 31/01/2025 - Facture FAC2025010171 : +15 792,83 € (Débit 411)
✅ 28/02/2025 - Encaissement FAC2025010171 : -15 792,83 € (Crédit 411)
❌ 02/10/2025 - Chèque N°2685339 (sans facture) : -22 805,69 € (Crédit 411)
```

**Calcul :**
```
Créance normale = 15 792,83 - 15 792,83 = 0 €
Encaissement orphelin = 22 805,69 €
Solde comptable total = 0 - 22 805,69 = -22 805,69 € ❌
```

**Diagnostic :** 
- Créance réelle = 0 € (facture payée)
- Avance client = 22 805,69 € (chèque orphelin)

---

### Cas 4 : Client avec Plusieurs Factures et Chèques

**Client : Société Générale**
```
✅ Facture A : +10 000 €
✅ Facture B : +8 000 €
✅ Encaissement Facture A : -10 000 €
✅ Encaissement partiel Facture B : -5 000 €
❌ Chèque orphelin : -15 000 €
```

**Calcul détaillé :**
```
Total factures = 10 000 + 8 000 = 18 000 €
Encaissements liés aux factures = 10 000 + 5 000 = 15 000 €
Créance réelle = 18 000 - 15 000 = 3 000 €
Encaissement orphelin = 15 000 €
Solde comptable = 18 000 - (15 000 + 15 000) = -12 000 € ❌
```

**Diagnostic :**
- Créance réelle = 3 000 € (Facture B partiellement payée)
- Avance client = 15 000 € (chèque orphelin)

## Formules Pratiques

### Pour Chaque Client

#### 1. Calcul de la Créance Normale
```
Créance Normale = Σ(Factures) - Σ(Encaissements liés aux factures)
```

#### 2. Identification des Orphelins
```
Encaissements Orphelins = Σ(Tous les encaissements) - Σ(Encaissements liés aux factures)
```

#### 3. Vérification
```
Solde Comptable 411 = Créance Normale - Encaissements Orphelins
```

## Régularisation

### Si Encaissements Orphelins > 0
```
Débit 411 (Créances clients)                [Montant orphelins]
    Crédit 4191 (Clients - Avances reçues)   [Montant orphelins]
```

### Résultat Après Régularisation
```
Nouveau Solde 411 = Créance Normale (≥ 0)
Solde 4191 = Encaissements Orphelins
```

## Exemple de Tableau de Travail

| Client | Factures | Encaissements Liés | Créance Normale | Encaissements Orphelins | Solde 411 Actuel | À Régulariser |
|--------|----------|-------------------|-----------------|------------------------|------------------|---------------|
| BNP Paribas | 15 792,83 € | 15 792,83 € | 0 € | 22 805,69 € | -22 805,69 € | 22 805,69 € |
| Société Générale | 0 € | 0 € | 0 € | 22 306,02 € | -22 306,02 € | 22 306,02 € |
| InfoVista Ltd | 4 445,71 € | 4 445,71 € | 0 € | 0 € | 0 € | 0 € |

## Points Clés

1. **Rapprochement facture par facture** obligatoire
2. **Seuls les orphelins** sont à régulariser
3. **Garder les créances normales** intactes
4. **Résultat final logique** : créances + avances

Cette méthode vous donne la **vraie situation** de chaque client !