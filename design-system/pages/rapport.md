# Écran 4 — Rapport : écarts au MASTER

> Ces règles priment sur [MASTER.md](../MASTER.md) pour cet écran. Contenu et états :
> [ECRANS.md](../ECRANS.md), écran 4. Maquette : [mockups/rapport.html](../mockups/rapport.html).

## Mise en page

- Largeur 1280 px au plus ; sections dans cet ordre : en-tête, alertes (hors ligne, non
  concluant, remarques importantes), synthèse, langages et projets, dépendances, fichiers
  écartés, remarques.
- Synthèse : une rangée de compteurs (`repeat(auto-fill, minmax(150px, 1fr))`), deux par
  ligne sur mobile. Tous les types de constats sont toujours là, même à zéro (un zéro dit
  « vérifié, rien trouvé » ; le chiffre est alors atténué). Les compteurs non nuls sont
  des boutons qui filtrent le tableau.
- Langages et projets côte à côte au-delà de 900 px (projets sur deux colonnes), l'un sous
  l'autre en dessous. Au-delà de 3 projets : une liste repliable, un projet par ligne
  (dossier, écosystèmes, nombre de dépendances et de constats).

## Densité du tableau

- Texte à 14 px, lignes d'au moins 52 px (nom et sous-ligne), cellules alignées en haut ;
  en-tête en majuscules 12 px, sur `--surface-2`, collant sous l'en-tête de l'application.
- Le nom du paquet est un bouton souligné en pointillé (ouvre le détail) ; les versions en
  chasse fixe ; une flèche (icône `arrow-right`, pas le caractère `→` que la police latine
  n'a pas) entre version utilisée et version proposée.
- Tri par défaut : gravité décroissante (l'ordre des constats du rapport), puis nom ;
  `aria-sort` sur la colonne triée.
- Plusieurs projets : une colonne « Projet » (masquée s'il n'y en a qu'un).
- Plus de 50 lignes : virtualisé (TanStack Virtual), en-tête et filtres gardés.
- Sous 768 px : une carte par dépendance (nom, puis chaque valeur avec son libellé).

## Panneau de détail

- 600 px, à droite, voile derrière ; plein écran sous 640 px. L'adresse garde le paquet
  ouvert (`?paquet=PyPI:flask`), pour un lien profond et le retour arrière.
- Constats : la gravité en badge à gauche, aligné en haut ; titre de l'avis (anglais,
  `lang="en"`), identifiants en chasse fixe 12 px, puis CVSS, « corrigée en », lien.
- Pied du panneau : « Fermer » et, principale, « Choisir la version de *paquet* »
  (écran 5, carte du paquet dépliée).

## Couleurs

- Une ligne de dépendance ne prend pas de couleur de fond selon sa gravité : seule la
  colonne « Gravité » porte le sens (badge), pour que le tableau reste lisible.
- Non concluant : badges violets à bord pointillé dans les colonnes Constats et Gravité
  (« Inconnue »).
