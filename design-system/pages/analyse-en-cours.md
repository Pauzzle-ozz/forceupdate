# Écran 3 — Analyse en cours : écarts au MASTER

> Ces règles priment sur [MASTER.md](../MASTER.md) pour cet écran. Contenu et états :
> [ECRANS.md](../ECRANS.md), écran 3.

## Mise en page

- Une seule colonne centrée, 640 px au plus : rien d'autre à faire pendant l'analyse.
  Pas de tableau, pas de panneau.
- Dans une carte : la source (nom en chasse fixe, chemin en dessous), les options en
  badges, la lame, la liste des étapes, le paquet en cours, le temps écoulé, « Annuler »
  (bouton secondaire, en bas à droite).

## La lame, en grand

- 8 px de haut ici (6 ailleurs). Indéterminée tant que `total` n'est pas connu
  (`reading`, `projects_found`), puis déterminée sur `done` / `total` à partir de
  `checking`.
- En sombre, sa lueur ; avec « réduire les animations », une barre fixe (rayée tant
  qu'elle est indéterminée).

## Les étapes

| Événement | Ligne |
|---|---|
| `reading` | « Lecture des fichiers » |
| `projects_found` | « 2 projets trouvés » (`total`) |
| `checking`, `package_checked` | « Vérification des paquets : 41 sur 64 », et dessous, en chasse fixe : `npm` `lodash` (le dernier paquet reçu) |
| `vulnerabilities_checked` | « Recherche des failles (OSV) » |
| `finished` | toutes cochées ; l'écran devient le rapport (même adresse), le focus va au titre |

## Le message de chargement (le clin d'œil)

Pendant la recherche des failles, sous la ligne fonctionnelle, en texte atténué :

> Recherche d'une perturbation dans la Force…

Une seule phrase, qui ne remplace jamais l'information (« Recherche des failles
(OSV) » reste au-dessus) ; hors de la zone `aria-live` : elle n'est pas annoncée.

## Annonces

- `aria-live="polite"` sur l'étape en cours seulement ; le nom du paquet n'est annoncé
  qu'au plus toutes les 5 s (sinon un lecteur d'écran lirait 64 noms).
- Analyse de plus de 10 s : « Les analyses suivantes iront plus vite : les réponses des
  registres restent en cache une heure. »

## Annuler

- « Annuler » envoie `DELETE /api/scans/{id}` ; le bouton passe en « Annulation… »
  (désactivé) jusqu'à `end` (`cancelled`), puis l'état « Analyse annulée » avec
  « Relancer ».
- Pas de confirmation : rien n'est perdu, l'analyse se relance.
