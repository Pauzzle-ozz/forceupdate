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

## Fait à E17

- La maquette est suivie, avec ces écarts :
  - pas de colonne « PR / MR », ni de compteur des PR ouvertes, ni de « Préparer N PR » : les PR
    arrivent à E18. D'ici là, l'action principale de la barre de sélection est « Analyser ces
    N dépôts » ;
  - « Recharger la liste » s'ajoute aux actions de l'en-tête (la liste est gardée le temps de la
    session) ;
  - une section « Analyser un autre dépôt » (un dépôt public, par son nom ou son adresse) sous
    le tableau, et sur l'état « aucun compte » ;
  - la forge n'a un filtre que s'il y en a plusieurs ; sous 1024 px, elle passe sous le nom du
    dépôt ;
  - un dépôt en attente de son tour dit « en attente de son tour », sans lame (rien n'avance
    encore) ; la carte « Failles » dit « analyse en cours » tant qu'un dépôt tourne (jamais
    « aucune connue » avant la fin) ;
  - **le tableau n'est pas virtualisé** (MASTER le veut au-delà de 50 lignes) : un compte a
    rarement plus de quelques centaines de dépôts, et chaque ligne est légère. À revoir si un
    compte en a des milliers.
- Le nom accessible d'un lien ou d'une case dit le dépôt (« Sélectionner octo/app », « Ouvrir
  octo/app sur GitHub (nouvel onglet) ») ; la case de tête dit combien de dépôts affichés elle
  prend, et passe à l'état indéterminé.

## Fait à E18

- La colonne « PR » est la dernière : `#41` en chasse fixe, souligné, avec l'icône
  `git-pull-request`, nommé « PR #41 de octo/app sur GitHub (nouvel onglet) » ; « pas de droit
  de push » (ou « archivé ») atténué ; « — » sinon. Elle s'appellera « PR / MR » quand GitLab
  sera là.
- Le compteur « PR ouvertes » est le sixième de la synthèse ; il ne filtre pas le tableau.

## Fait à E19

- La colonne s'appelle « PR / MR » quand la liste a des dépôts GitLab (« PR » sinon), le
  compteur « PR et MR ouvertes » ; « Préparer 1 PR et 1 MR » prépare **un seul**
  récapitulatif pour toutes les forges sélectionnées (au lieu d'un par forge).
- Une instance GitLab se dit « GitLab (hôte) » partout où la forge est nommée ; ses requêtes
  restantes ont leur ligne, comme celles de chaque compte.
- Deux dépôts de même nom (le même `owner/nom` sur GitHub et sur GitLab) : rien ne change à
  l'écran (la colonne Forge les distingue), mais leur case et leur lien disent la forge aux
  lecteurs d'écran.
- La barre de sélection suit la maquette : « Préparer N PR » en principale, à droite ;
  « Analyser ces N dépôts » en secondaire. Le nombre de mises à jour cochées par défaut reste
  dit (« N mises à jour cochées par défaut »).
