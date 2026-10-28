# Écran 7 — Mes dépôts : écarts au MASTER

> Ces règles priment sur [MASTER.md](../MASTER.md) pour cet écran. Contenu et états :
> [ECRANS.md](../ECRANS.md), écran 7. Maquette (données fictives) :
> [mockups/depots.html](../mockups/depots.html).

## Mise en page

- En tête, les comptes en pastilles (forge en texte et icône neutre, identifiant en
  chasse fixe, droits en badge) ; puis la synthèse multi-dépôts (même compteurs que le
  rapport, à l'échelle des dépôts), puis le tableau.
- Les alertes d'organisation (accès restreint) et de compte (token refusé) se placent
  au-dessus des comptes.
- Requêtes d'API restantes : une ligne discrète à droite du titre de la synthèse ; en
  avertissement sous 10 %.

## Sélection et actions groupées

- Une case par ligne, et une case d'en-tête à trois états (aucune, quelques-unes,
  toutes les lignes filtrées).
- Dès qu'une ligne est cochée, une **barre d'actions collante** en bas du tableau :
  « *N* dépôts sélectionnés », le nombre de mises à jour pré-cochées, « Analyser de
  nouveau » (secondaire), « Préparer *N* PR et *M* MR » (principale ; GitLab dit MR). Sous
  640 px, elle colle au bas de l'écran, sur toute la largeur.
- Lignes sélectionnées sur `--primary-soft`.

## Le tableau

- Dépôt : `owner/` atténué puis le nom, en chasse fixe ; cadenas pour un dépôt privé
  (icône nommée « privé »).
- Analyse : les chiffres en badges (critique plein, puis failles, puis « à mettre à
  jour ») ; en cours, une lame de 4 px et « 18 sur 45 paquets » ; « non concluant » avec
  la raison en clair.
- PR / MR : le numéro tel que l'écrit la forge (`#41` sur GitHub et Bitbucket, `!12` sur
  GitLab), lien vers la forge (nouvel onglet).
- Archivés, forks et vides : masqués par défaut, leur nombre dit à côté du titre, avec
  « Les afficher ». Lecture seule : badge `eye-off` « lecture seule », colonne PR « pas de
  droit de push ».
- Sous 768 px : une carte par dépôt.

## Analyse groupée

- Une carte au-dessus du tableau : « Analyse de 28 dépôts : 12 terminés », la lame
  d'ensemble, la concurrence et les requêtes utilisées, « Annuler » (annule les analyses
  pas encore finies ; celles finies restent).
