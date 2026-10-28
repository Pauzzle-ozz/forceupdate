# Écran 5 — Mise à jour : écarts au MASTER

> Ces règles priment sur [MASTER.md](../MASTER.md) pour cet écran. Contenu et états :
> [ECRANS.md](../ECRANS.md), écran 5. Maquette :
> [mockups/mise-a-jour.html](../mockups/mise-a-jour.html).

## Mise en page

- Fil d'étapes sous le titre : Choisir → Vérifier → Appliquer → Résultat (deux étapes
  seulement pour un fichier envoyé : Choisir → Vérifier, puis Télécharger). Sous 640 px,
  sans traits entre les étapes.
- Étapes 1 et 2 : contenu à gauche, **colonne de 340 px à droite**, collante, avec le
  récapitulatif et l'action principale. Sous 1024 px, la colonne passe sous le contenu
  et une **barre collante en bas** reprend le nombre coché et l'action (« Vérifier le
  plan »), pour qu'elle reste à portée.
- Étapes 3 et 4 : une colonne, 760 à 860 px.

## Les cartes de mise à jour

- Groupées par lockfile (titre : écosystème, lockfile, outil), dans l'ordre du rapport.
- En-tête de carte : case du paquet (nom en chasse fixe, 600), « directe » ou
  « indirecte », version utilisée, nombre de failles (badge), « par le lockfile seul »
  pour une indirecte ; la `note` en dessous si elle existe.
- Options : une par ligne, séparées en pointillé, de la plus ancienne à la plus récente
  (l'ordre de l'API) ; toute la ligne est la cible du bouton radio. L'option choisie prend
  `--primary-soft`. Badge « proposée » sur l'option `selected`.
- Dans une option : version (chasse fixe, 600), écart, raisons en clair (« dernier
  correctif », « dernière mineure », « dernière version », « corrige les failles »,
  « remplace une version retirée »), puis en dessous : failles corrigées (« Corrige 2
  failles sur 6, en laisse 4 », ou « Corrige les 6 failles » en vert avec `shield-check`),
  failles apportées (rouge, `shield-alert`), avertissements (couleur d'avertissement,
  `triangle-alert`), réécritures (« `requirements.in` : ==0.12 → ==0.12.5 », ou « aucun
  manifeste réécrit : `requirements.txt` seul »).
- Option `manual` : grisée (opacité .6), radio désactivé, badge « à faire à la main », la
  raison en clair.
- Une carte sans option (paquet malveillant) : case désactivée, badge critique, la note
  en rouge.

## Diffs et lockfiles

- Diff : chasse fixe 13 px, deux colonnes de numéros (avant, après), une colonne `+`/`−`
  en gras, fond de ligne `--diff-add-bg` / `--diff-del-bg`, ligne de bloc `@@` sur
  `--surface-2`. Un cadre par fichier, défilant à l'horizontale, focalisable (`tabindex=0`,
  `role="region"`, nom « Diff de *fichier* »). Plus de 400 lignes : replié, « Afficher le
  diff ».
- Lockfile : carte avec l'icône `lock`, le nom, les mises à jour portées ; à droite
  « *outil* trouvé » (vert) ou « *outil* absent » (avertissement) ; la commande (bloc
  avec « Copier ») ; les avertissements du plan en liste.

## Garde-fou et confirmation

- Garde-fou git dans la colonne de droite, au-dessus du bouton : vert « Git peut tout
  défaire » (`uncommitted` vide), avertissement « Hors d'un dépôt git » (`null`),
  avertissement « Changements pas encore commités » (liste) ; dans ce dernier cas,
  « Appliquer » devient « Appliquer quand même… » (bouton risqué) qui ouvre un
  `AlertDialog` : focus sur « Annuler », « Appliquer quand même » en rouge.
- Pendant l'application : aucun bouton d'annulation, la phrase le dit.

## Résultat

- Une carte par lockfile, statut en badge à droite (« régénéré », « commande à lancer »,
  « échec, fichiers remis », « défait ») ; une ligne par mise à jour avec sa version
  obtenue et son badge (« version exacte » vert ; « plus haute que choisie » info ;
  « retenue par *paquet version* » avertissement).
- Sortie d'un outil en échec : bloc en chasse fixe, 12 dernières lignes, défilant.
