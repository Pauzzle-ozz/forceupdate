# Les forges : GitHub, GitLab, Bitbucket

forceupdate lit les dépôts d'une forge par son API, sans les cloner, puis ouvre une pull
request par dépôt à mettre à jour (une merge request sur GitLab). Tout se passe dans
l'interface (`forceupdate ui`), sur trois écrans :

- « Comptes » (`/comptes`) : connecter et déconnecter ses comptes ;
- « Mes dépôts » (`/depots`) : les dépôts de ces comptes, leur analyse, la sélection ;
- le récapitulatif des PR (`/pr`) : ce que chaque PR fera, l'envoi, les liens.

Ce qui est pris :

| Forge | Hôte | Se connecter | Proposition |
|---|---|---|---|
| GitHub | `github.com` | page d'autorisation, code (device flow), token collé, `gh` | PR, `#41` |
| GitLab | `gitlab.com` | page d'autorisation, token collé | MR, `!12` |
| GitLab auto-hébergé | une instance, par son adresse | token collé | MR, `!12` |
| Bitbucket Cloud | `bitbucket.org` | page d'autorisation, token d'API Atlassian collé | PR, `#41` |

Pas pris : Bitbucket Data Center (auto-hébergé, une autre API), et GitHub hors de
`github.com` (GitHub Enterprise Server).

Analyser ne demande que le réseau (et git pour un très gros dépôt, voir
[Quand un clone superficiel est fait](#quand-un-clone-superficiel-est-fait)). Ouvrir une PR
demande git sur l'ordinateur.

## Se connecter

### Avant de commencer

- **Ouvrir l'interface par l'adresse que donne `forceupdate ui`** :
  `http://127.0.0.1:<port>/…`, jeton compris. Les forges ne renvoient qu'à `127.0.0.1`. Par
  `localhost`, la connexion par la page d'autorisation est refusée : « GitHub ne revient que
  vers 127.0.0.1 : ouvrir l'interface par http://127.0.0.1:<port> (l'adresse que donne
  « forceupdate ui »), ou se connecter avec un code. »
  Le port n'importe pas (`--port`) : les trois forges acceptent n'importe quel port sur
  `127.0.0.1`.
- **Le trousseau du système doit marcher.** Sinon « Comptes » affiche « Trousseau
  indisponible » et aucune connexion ne se fait. Sous Linux, voir
  [Le trousseau sous Linux](#le-trousseau-sous-linux).
- **Un compte par forge et par hôte** : un GitHub, un gitlab.com, un par instance GitLab, un
  Bitbucket. Se connecter de nouveau remplace le compte.

À la connexion, forceupdate demande à la forge qui est connecté et ce que le token permet,
puis range le token. L'écran relit ces droits à chaque ouverture, et par « Vérifier les
droits ».

### GitHub

Quatre façons, sur la carte GitHub :

1. **« Se connecter avec GitHub »** (OAuth). GitHub demande d'autoriser forceupdate, puis
   revient sur l'ordinateur (`http://127.0.0.1:<port>/oauth/github/callback`). Portées
   demandées : `repo` (lire les dépôts privés, pousser une branche, ouvrir une PR) et
   `read:org` (lister les organisations, pour signaler celles qui restreignent l'accès des
   applications). La demande expire après 10 minutes.
2. **« Se connecter avec un code »** (device flow), sous « Autres façons de se connecter » :
   quand le retour vers l'ordinateur ne marche pas. Un code s'affiche en grand, avec
   « Copier ». Le saisir sur `github.com/login/device` (« Ouvrir github.com/login/device »),
   puis autoriser forceupdate. Mêmes portées. L'écran attend, et dit l'heure où le code
   expire.
3. **« Reprendre le compte de gh »** : seulement si GitHub CLI (`gh`) est installé.
   forceupdate lit son token (`gh auth token`) et le range dans son propre trousseau. `gh` n'est
   pas connecté : « gh n'est pas connecté à github.com (…) : lancer « gh auth login », ou se
   connecter autrement. »
4. **Un token collé** (« Token GitHub », puis « Connecter avec ce token ») : un token classic
   avec les portées `repo` et `read:org` (le lien « Créer un token sur github.com » les
   pré-coche), ou un token fine-grained (voir [Droits non vérifiés](#droits-non-vérifiés)).

Un token obtenu par OAuth ou par un code n'expire pas, comme celui de `gh` : forceupdate n'a
rien à renouveler.

### GitLab

- **gitlab.com, « Se connecter avec GitLab »** (OAuth avec PKCE). Portée `api`. Retour sur
  `http://127.0.0.1:<port>/oauth/gitlab/callback`.
- **gitlab.com, un token collé** : « Un token d'accès personnel avec la portée api ». Le
  lien « Créer un token sur gitlab.com » pré-remplit son nom et sa portée.
- **Une instance auto-hébergée**, dans le groupe « Instances auto-hébergées » de la carte
  GitLab : « Adresse de l'instance » (`https://gitlab.example.com`, ou
  `https://gitlab.example.com:8443`), « Token de l'instance » (le lien « Créer un token sur
  <hôte> » apparaît une fois l'adresse lisible), puis « Connecter l'instance ». Seulement en
  https, sans chemin ni identifiants dans l'adresse : « Adresse d'instance refusée : donner
  https://hôte (ou https://hôte:port), sans chemin ni identifiants. Le token ne part jamais en
  clair (http). » Pas d'OAuth sur une instance : il faudrait y enregistrer forceupdate.

Chaque instance connectée a son bloc (« Vérifier les droits », « Se déconnecter… »). GitLab
n'a ni code ni `gh`.

### Bitbucket Cloud

- **« Se connecter avec Bitbucket »** (OAuth). Retour sur
  `http://127.0.0.1:<port>/oauth/bitbucket/callback`. Les portées sont celles de
  l'application, pas de la demande : `account`, `email`, `repository:write`,
  `pullrequest:write`.
- **Un token d'API Atlassian collé**, créé sur `id.atlassian.com` (« Créer un token sur
  id.atlassian.com ») par « Create API token with scopes », application Bitbucket, avec ces six
  portées :

  ```
  read:user:bitbucket
  read:workspace:bitbucket
  read:repository:bitbucket
  write:repository:bitbucket
  read:pullrequest:bitbucket
  write:pullrequest:bitbucket
  ```

  Aucune n'en comprend une autre : il les faut toutes. Les « app passwords » ne marchent
  plus (depuis le 28 juillet 2026).

### Les droits nécessaires

| Forge | Portées du token | Sur le dépôt, pour une PR |
|---|---|---|
| GitHub, OAuth ou code | `repo`, `read:org` (demandées par forceupdate) | le droit de push |
| GitHub, token classic | `repo` ; `read:org` pour signaler les organisations restreintes | le droit de push |
| GitHub, token fine-grained | « Contents » et « Pull requests » en écriture, « Metadata » en lecture | le droit de push |
| GitLab (OAuth ou token) | `api` | le rôle Developer au moins |
| Bitbucket, OAuth | celles de l'application (ci-dessus) | `write` ou `admin`, ou administrateur du workspace |
| Bitbucket, token d'API | les six portées ci-dessus | `write` ou `admin`, ou administrateur du workspace |

La carte d'un compte connecté dit ce que permet son token :

- « Lecture et PR » (« Lecture et MR » sur GitLab), « dépôts publics et privés » : tout est là ;
- « Lecture et PR », « dépôts publics seulement » : un token classic à la portée
  `public_repo` (GitHub) ;
- « Lecture seule » : les dépôts se lisent, aucune PR ne s'ouvre (GitHub sans `repo` : les
  dépôts publics seulement ; GitLab avec `read_api` ; Bitbucket sans l'écriture) ;
- « Droits non vérifiés » : voir ci-dessous.

Sous « À savoir sur ces droits », la carte dit ce qui manquera. Par exemple : « Sans la
portée read:org, les organisations qui restreignent l'accès des applications ne pourront pas
être signalées. »

Un dépôt où le compte n'a pas le droit de push se liste et s'analyse, mais n'a pas de PR :
« lecture seule » et « pas de droit de push » dans « Mes dépôts », « lecture seule : pas de
droit de push » au récapitulatif.

### Droits non vérifiés

La forge ne dit pas ce que permettent certains tokens : un token fine-grained de GitHub (il n'a
pas d'en-tête de portées), un token d'API Atlassian, ou un token GitLab dont GitLab ne rend
pas les portées. Le compte se connecte et ses dépôts se lisent, mais on ne saura s'il peut
pousser et ouvrir une PR qu'en essayant. La carte affiche « Droits non vérifiés » (« la forge
ne les dit pas pour ce token »), des portées « non données par la forge », et ce qu'il faut :

- GitHub : « Token fine-grained : GitHub ne dit pas ses droits. Pour les dépôts à mettre à
  jour, il lui faut « Contents » et « Pull requests » en écriture, et « Metadata » en
  lecture. »
- GitLab : « GitLab ne dit pas les droits de ce token. Pour ouvrir des MR, il lui faut la
  portée api, et le rôle Developer sur les projets. »
- Bitbucket : « Bitbucket ne dit pas les droits de ce token. Pour ouvrir des PR, un token
  d'API Atlassian a besoin des portées … » (les six).

Un push ou une PR refusés (403) le disent ensuite dans l'erreur du dépôt, à l'envoi. Avec
un token fine-grained, l'erreur ajoute : « Token fine-grained : il lui faut « Contents » et
« Pull requests » en écriture sur ce dépôt. »

### Où est le token

- **Dans le trousseau du système** : le Gestionnaire d'identification de Windows, le
  trousseau de macOS, Secret Service sous Linux (GNOME Keyring, KWallet). Au service
  `forceupdate`, sous le nom `<forge>:<hôte>` : `github:github.com`, `gitlab:gitlab.com`,
  `gitlab:gitlab.example.com`, `bitbucket:bitbucket.org`. Un token qui expire y est rangé
  avec son refresh token et son heure d'expiration. Un secret trop long pour une entrée
  (Windows en refuse au-delà de 1 280 caractères ; un token d'OAuth de Bitbucket en a plus
  de 2 000) est rangé en morceaux : `bitbucket:bitbucket.org#1`, `#2`…
- **Nulle part ailleurs.** Il ne va jamais au navigateur, ni dans un journal, un message ou
  un rapport. git le reçoit sans qu'il soit dans ses arguments, et ne le garde pas : rien dans
  `.git/config`, rien dans le Gestionnaire d'identification de Windows (voir
  [git et sa configuration](#git-et-sa-configuration)).
- **Le reste du compte** (identifiant, nom, droits, façon de se connecter, dates) est dans
  `accounts.json`, sans aucun secret : `%LOCALAPPDATA%\forceupdate` sous Windows,
  `~/.local/state/forceupdate` sous Linux, `~/Library/Application Support/forceupdate` sous
  macOS.

Un compte n'existe que si son token est dans le trousseau : effacé à la main du trousseau,
le compte disparaît de l'écran.

### Renouvellement

| Token | Durée | Renouvelé |
|---|---|---|
| GitHub, par OAuth ou par un code | sans expiration (comme `gh`) | jamais : rien à renouveler |
| GitHub, collé ou repris de `gh` | celle que lui donne GitHub | jamais |
| GitLab, par OAuth | 2 h | oui, par son refresh token, qui ne sert qu'une fois |
| GitLab, token personnel | jusqu'à sa date d'expiration | jamais : en coller un nouveau |
| Bitbucket, par OAuth | 2 h | oui, par son refresh token, remplacé à chaque fois |
| Bitbucket, token d'API | celle que lui donne Atlassian | jamais |

Un token qui se renouvelle l'est avant de servir s'il expire dans moins de 5 minutes, et
quand la forge le refuse. Un seul renouvellement à la fois pour un compte, d'où qu'il vienne
(l'écran, une analyse, un envoi). L'échéance d'un token personnel de GitLab est dite sur sa
carte : « Ce token expire le … : il faudra en coller un nouveau. »

**Un token refusé** (révoqué sur la forge, expiré, refresh token qui ne marche plus) : le
compte reste affiché, avec « GitHub refuse le token » (ou GitLab, Bitbucket) et la raison.
Pour un refresh token de Bitbucket : « Bitbucket ne renouvelle plus le token (accès retiré à
forceupdate, ou resté trop longtemps sans servir) : se reconnecter. » La carte propose « Se
reconnecter », ou, sans page d'autorisation possible, « Se déconnecter, puis coller un nouveau
token. » « Mes dépôts » le dit aussi (« GitHub refuse le token de <compte> »,
« Reconnecter GitHub »). Une forge qui ne répond pas : « Droits non revérifiés », le compte
reste.

### Se déconnecter

« Se déconnecter… », puis la confirmation. Le token est effacé du trousseau (ses morceaux
compris), et le compte de `accounts.json`. Les analyses déjà faites restent.

| Connecté par | À la déconnexion |
|---|---|
| GitHub, OAuth ou code | le token est aussi révoqué auprès de GitHub |
| GitLab, OAuth | le token est aussi révoqué auprès de gitlab.com |
| Bitbucket, OAuth | pas révoqué : Bitbucket ne le permet pas par son API. Le bouton « Retirer l'accès sur bitbucket.org » mène à `https://bitbucket.org/account/settings/app-authorizations/` |
| un token collé (toutes les forges) | pas révoqué : il appartient à la personne. Le révoquer sur la forge si besoin |
| `gh` | pas révoqué : `gh` reste connecté |

Si la forge ne répond pas au moment de révoquer, le message le dit et donne l'adresse où le
faire à la main : `https://github.com/settings/applications`,
`https://gitlab.com/-/user_settings/applications`.

### Le trousseau sous Linux

forceupdate range les tokens par [keyring](https://pypi.org/project/keyring/), qui parle à
Secret Service sous Linux. Un serveur ou WSL n'en ont souvent pas. Aucun compte ne se
connecte alors, et « Comptes » dit pourquoi : « Aucun trousseau du système n'est utilisable :
les tokens ne peuvent pas être gardés. Sous Linux (serveur, WSL), installer un service de
trousseau (GNOME Keyring, KWallet), ou en choisir un autre par PYTHON_KEYRING_BACKEND : voir
la documentation. »

forceupdate n'écrit jamais un token dans un fichier en clair. Deux solutions :

1. **Installer un Secret Service.** Par exemple GNOME Keyring : les paquets `gnome-keyring`
   et `dbus`. Dans une session de bureau, rien de plus. Sur un serveur sans session
   graphique, lancer forceupdate dans une session D-Bus, le trousseau déverrouillé par sa
   phrase de passe :

   ```bash
   dbus-run-session -- sh -c 'echo -n "<phrase>" | gnome-keyring-daemon --unlock; forceupdate ui'
   ```

   À vérifier sur une vraie machine : cette commande n'a pas encore été essayée.

2. **Choisir un autre trousseau**, par le mécanisme de keyring. Par exemple un fichier
   chiffré par une phrase de passe, avec `keyrings.cryptfile` :

   ```bash
   uv tool install forceupdate --with keyrings.cryptfile
   PYTHON_KEYRING_BACKEND=keyrings.cryptfile.cryptfile.CryptFileKeyring forceupdate ui
   ```

   Sa phrase de passe est demandée dans le terminal, ou lue dans
   `KEYRING_CRYPTFILE_PASSWORD`. keyring lit aussi son backend dans son fichier
   `keyringrc.cfg`.

## Enregistrer sa propre application

forceupdate arrive avec ses applications, enregistrées par son auteur : une OAuth App
GitHub, une application de gitlab.com, un « OAuth client » Bitbucket. Le secret de celles de
GitHub et de Bitbucket est embarqué dans l'outil, comme celui de `gh` : il ne permet que de
présenter la page d'autorisation au nom de forceupdate, jamais d'obtenir un token sans
l'accord de la personne.

Sa propre application sert pour un fork, une règle d'entreprise, ou une organisation qui
n'autorise que les siennes. Elle se passe à forceupdate par des variables d'environnement,
lues au démarrage de `forceupdate ui` :

| Variable | Forge | Sens |
|---|---|---|
| `FORCEUPDATE_GITHUB_CLIENT_ID` | GitHub | le client id de l'OAuth App |
| `FORCEUPDATE_GITHUB_CLIENT_SECRET` | GitHub | son secret ; sans lui, pas de « Se connecter avec GitHub » (le code, le token collé et `gh` restent), et la déconnexion ne révoque pas |
| `FORCEUPDATE_GITLAB_CLIENT_ID` | GitLab (gitlab.com) | l'« Application ID » ; pas de secret |
| `FORCEUPDATE_BITBUCKET_CLIENT_ID` | Bitbucket | le client id de l'OAuth client |
| `FORCEUPDATE_BITBUCKET_CLIENT_SECRET` | Bitbucket | son secret ; sans les deux, pas de « Se connecter avec Bitbucket » : le token d'API Atlassian reste |

Dès qu'un client id est donné, celui de forceupdate et son secret ne servent plus pour cette
forge.

```bash
export FORCEUPDATE_GITHUB_CLIENT_ID=Ov23li…
export FORCEUPDATE_GITHUB_CLIENT_SECRET=…
forceupdate ui
```

```powershell
$env:FORCEUPDATE_GITHUB_CLIENT_ID = "Ov23li…"
$env:FORCEUPDATE_GITHUB_CLIENT_SECRET = "…"
forceupdate ui
```

Une organisation GitHub qui restreint l'accès des applications OAuth autorise chaque
application à part : avoir autorisé celle de forceupdate ne vaut pas pour la sienne.

### GitHub : une OAuth App

Une OAuth App, pas une GitHub App : un clic donne accès à tous les dépôts du compte, sans
installer l'application sur chaque compte et organisation.

1. Sur github.com : Settings → Developer settings → OAuth Apps → « New OAuth App » (ou les
   réglages d'une organisation, même chemin).
2. Un nom (celui que montre la page d'autorisation) et une « Homepage URL ».
3. « Redirect URIs » : `http://127.0.0.1/oauth/github/callback`, sans port (GitHub accepte
   n'importe quel port sur `127.0.0.1`). Un formulaire plus ancien l'appelle « Authorization
   callback URL ».
4. Device Flow coché (« Enable Device Flow ») : sinon « Se connecter avec un code » échoue
   (« Le device flow n'est pas activé pour l'application forceupdate sur GitHub. »).
5. « Expire user access tokens » décoché. GitHub le coche d'office ; coché, ses tokens
   durent 8 h, et forceupdate ne les renouvelle pas : le compte serait refusé au bout de 8 h.
6. Créer un secret (« Generate a new client secret »), puis le passer avec le client id.

### GitLab : une application de gitlab.com

1. Sur gitlab.com : avatar → « Edit profile » → « Access » → « Applications ».
2. Un nom, et l'adresse de retour `http://127.0.0.1/oauth/gitlab/callback`, sans port
   (GitLab accepte n'importe quel port sur `127.0.0.1`).
3. « Confidential » décoché : PKCE remplace le secret, et forceupdate n'en envoie pas.
4. La portée `api`. `read_api` ne permet pas d'ouvrir une MR, `write_repository` ne donne
   pas l'API.
5. Passer l'« Application ID » par `FORCEUPDATE_GITLAB_CLIENT_ID`.

Seulement pour gitlab.com : une instance auto-hébergée se connecte par un token.

### Bitbucket : un « OAuth client »

Il se crée dans un workspace que l'on administre. Bitbucket n'a ni client sans secret ni
PKCE (accepté, pas vérifié) : le secret est nécessaire.

1. Workspace settings → Apps and features → « OAuth clients » → « Create OAuth client ».
2. Onglet Details : un nom, une description, une « Learn more URL ».
3. Onglet Authorization : « Authorization code » et « Refresh token » cochés. Jamais
   « Client credentials » : avec un secret embarqué, il donnerait un accès sans la personne.
4. Onglet Scopes : Account (Read, Email), Repositories (Read, Write), Pull requests (Read,
   Write). Une portée oubliée : « Bitbucket refuse les portées demandées : elles ne sont pas
   toutes cochées dans les réglages de l'application forceupdate. »
5. L'adresse de retour : `http://127.0.0.1/oauth/bitbucket/callback` (n'importe quel port
   est accepté).
6. Passer le client id et le secret par `FORCEUPDATE_BITBUCKET_CLIENT_ID` et
   `FORCEUPDATE_BITBUCKET_CLIENT_SECRET`.

## Analyser les dépôts sans les cloner

### La liste des dépôts

« Mes dépôts » liste les dépôts de tous les comptes connectés, ensemble :

- **GitHub** : les siens, ceux où le compte collabore, ceux de ses organisations ;
- **GitLab** : les projets dont le compte est membre, directement ou par un groupe,
  sous-groupes compris (chemin complet : `groupe/sous-groupe/projet`) ;
- **Bitbucket** : workspace par workspace (Bitbucket ne liste plus tous les dépôts d'un
  coup depuis avril 2026).

Chaque dépôt est marqué privé, archivé, fork, vide, et avec ou sans droit de push.
Archivés, forks et vides sont masqués par défaut (« Les afficher »), comme les « Dépôts
exclus » de l'écran Réglages (`github.com/owner/repo`, `gitlab.com/groupe/*`) : « Analyser
tous les dépôts » les saute, et un dépôt exclu n'a jamais de PR. Bitbucket Cloud n'a pas de
dépôt archivé.

La liste est demandée aux forges une fois par session. « Recharger la liste » la redemande.

### Ce qui est téléchargé

Pour chaque dépôt, au dernier commit de sa branche par défaut :

1. **l'arborescence**, sans les dossiers que forceupdate ne parcourt jamais (`node_modules`,
   `vendor`, environnements virtuels…). Elle donne les langages et les projets ;
2. **les seuls fichiers que lit l'analyse** : la configuration (`forceupdate.toml`,
   `pyproject.toml`), les manifestes et les lockfiles, puis ce qu'ils désignent (les `-r` et
   `-c` d'un `requirements.txt`, le `pyproject.toml` racine d'un workspace uv, un
   `pnpm-workspace.yaml` parent, la configuration des registres : `.npmrc`, `nuget.config`…).
   Jusqu'à ce que rien de nouveau ne soit demandé, 8 tours au plus. Un `setup.py`, que
   forceupdate ne lit pas, n'est jamais téléchargé ;
3. puis la même analyse qu'un dossier de l'ordinateur.

Les fichiers sont lus au commit de l'arborescence, même si la branche avance entre-temps.
Un fichier trop gros (plus de 2 Mo, 50 Mo pour un lockfile) n'est pas lu, comme en local :
le rapport le dit. GitLab ne donne pas les tailles : ses fichiers sont téléchargés, puis
écartés à la lecture. Les fichiers téléchargés sont rangés dans le
[dossier de travail du serveur](#le-dossier-de-travail-du-serveur) : le récapitulatif d'une
PR s'en sert.

Quatre dépôts s'analysent à la fois. « Annuler » arrête une analyse groupée ; ce qui est
fini reste.

### Quand un clone superficiel est fait

**À l'analyse**, seulement si la forge ne rend pas toute l'arborescence :

- GitHub : plus de 100 000 entrées ;
- GitLab : plus de 100 pages de 100 entrées ;
- Bitbucket : plus de 12 niveaux de dossiers, plus de 100 pages, ou une arborescence trop
  lente pour Bitbucket.

Le dépôt est alors cloné (`--depth 1`, la branche par défaut), et c'est le clone qui est
analysé, comme un dossier : le rapport dit « cloné ». Sans git, ou si le clone échoue,
l'analyse reste partielle : le rapport le dit, et le dépôt n'est jamais « à jour ».

**À l'envoi d'une PR**, toujours (voir [L'envoi](#lenvoi)).

### Sous-modules

Un sous-module est un autre dépôt, à un commit. Il n'est pas analysé, ni par l'API, ni dans
un clone (fait sans eux). Le rapport le dit : « sous-module git : pas analysé (un autre
dépôt, à analyser à part). » Pour l'analyser : le dépôt lui-même, dans « Mes dépôts » ou par
« Analyser un autre dépôt ». Un sous-module rangé sous un dossier jamais parcouru (`vendor/`…)
n'est pas signalé.

### Organisations GitHub restreintes

Une organisation peut restreindre l'accès des applications OAuth : ses dépôts privés
n'apparaissent qu'après l'accord d'un de ses propriétaires. « Mes dépôts » le dit au lieu
de les cacher : « L'organisation <nom> limite l'accès des applications », avec « Demander
l'accès sur GitHub » (`https://github.com/settings/applications`). Ses dépôts publics sont
listés. Une organisation qui exige le SSO (SAML) : « L'organisation <nom> exige d'autoriser
le token pour son SSO », avec « Autoriser le token sur GitHub ». Il faut la portée
`read:org` pour les voir.

### Les requêtes d'API

| Forge | Limite | Affichée |
|---|---|---|
| GitHub | 5 000 requêtes par heure avec un token, 60 sans | oui |
| GitLab | par minute, parfois par point d'API | oui |
| Bitbucket | 1 000 requêtes par heure sur les dépôts | non : Bitbucket ne les dit pas |

« Mes dépôts » montre les requêtes restantes d'après la dernière réponse de la forge (en
avertissement sous 10 %), et une analyse groupée celles qu'elle a utilisées. Une limite
atteinte dit quand elle se lève : « Limite de l'API GitHub atteinte (5000 requêtes par
heure) : elle se lève à 19:00. »

### Un dépôt public d'un autre compte

« Analyser un autre dépôt » (« Dépôt public : owner/nom ou adresse ») prend `owner/nom`,
qui désigne un dépôt GitHub, ou l'adresse du dépôt sur sa forge :
`https://gitlab.com/groupe/sous-groupe/projet` (une page du projet aussi,
`…/-/tree/main`), `https://bitbucket.org/workspace/dépôt`, `git@github.com:owner/nom.git`.
Une instance GitLab connectée se reconnaît à son hôte. Avec le token du compte connecté à
cette forge, sans token sinon (GitHub : 60 requêtes par heure). Le dépôt n'entre pas dans la
liste, et n'a pas de PR : une PR se prépare pour un dépôt de la liste des comptes connectés.

## Ce que fait une PR

Sur GitLab, une MR : tout ce qui suit vaut pour elle.

### Le récapitulatif

Depuis « Mes dépôts », cocher des dépôts, puis « Préparer 3 PR » (« Préparer 1 PR et 1 MR »
s'il y a plusieurs forges). Depuis le rapport d'un dépôt, « Préparer la PR » mène à l'écran
de mise à jour, pour choisir. **Rien n'est cloné ni poussé** : la sélection se prépare sur
les fichiers téléchargés à l'analyse, en une seconde.

Pour chaque dépôt prêt :

- « nouvelle PR », ou « met à jour la PR #41 » si elle est déjà ouverte ;
- `forceupdate/dependencies → main : la branche visée n'est jamais poussée directement`, et
  le commit analysé ;
- les mises à jour (versions, écart, failles corrigées), celles qui ne seront pas
  appliquées et pourquoi, les fichiers réécrits et leurs diffs ;
- les lockfiles : « régénéré par npm », ou « npm absent » et la commande que donnera la
  description ;
- « Modifier la sélection » (l'écran de mise à jour, pour ce dépôt), « Voir le rapport ».

La sélection par défaut est celle du rapport : correctifs, mineures et corrections de
failles cochés, majeures jamais cochées d'office (sauf une sélection réglée à « majeures »,
voir [la configuration](USAGE.md#configuration)).

**Pas coché par défaut** : un dépôt à l'« analyse non concluante » (des paquets n'ont pas pu
être vérifiés, ou l'arborescence était incomplète), et un dépôt dont la dernière PR a été
fermée sans fusion (voir plus bas). C'est à la personne de les cocher.

**Sautés**, avec la raison : « archivé : lecture seule », « lecture seule : pas de droit de
push », « vide », « pas encore analysé », « analyse en cours », « analyse échouée », « exclu
dans les réglages : pas de PR », « aucune mise à jour cochée », « rien à mettre à jour ».

Puis « Envoyer la PR », ou « Envoyer 3 PR ». Les récapitulatifs ne vivent que le temps de
la session du serveur.

### L'envoi

Les dépôts cochés partent un à la fois, jamais pendant une mise à jour locale. Pour chacun :

1. forceupdate demande à la forge qui est connecté : ce compte sera l'auteur du commit ;
2. « clone superficiel de la branche par défaut » ;
3. « réécriture des manifestes et régénération des lockfiles » : la sélection est préparée
   de nouveau sur le clone. Un fichier qui a changé depuis l'analyse voit ses options
   sautées (« a changé depuis l'analyse ») ; le reste part. Les lockfiles sont régénérés par
   leur outil, sans les scripts du projet. Pour une PR, ce que forceupdate propose en plus
   est toujours fait : le lockfile npm refait par le npm qu'attend le projet, `go mod vendor`
   pour un module qui a un `vendor/` ;
4. un commit ;
5. « push de la branche forceupdate/dependencies » ;
6. « ouverture ou mise à jour de la PR ».

Le clone est effacé ensuite. Un dépôt qui échoue n'arrête pas les autres. Un compte dont le
token est refusé non plus : ses dépôts échouent, et l'écran le dit (« Un compte refuse son
token », qui mène à « Comptes »). Un envoi ne s'annule pas depuis l'interface.

Le résultat donne, par dépôt, le lien (« Voir la PR #41 sur GitHub ») ou l'erreur, et le
total : « 1 PR ouverte · 1 MR ouverte · 1 mise à jour · 1 en échec ».

### La branche `forceupdate/dependencies`

- **Jamais de push sur la branche par défaut.** La PR va de `forceupdate/dependencies`, dans
  le dépôt même, vers la branche par défaut.
- **La branche est remplacée à chaque envoi** : un seul commit, refait sur la branche par
  défaut du moment, poussé avec `--force-with-lease` sur le commit qu'on a vu. Si quelqu'un
  change la branche entre-temps, rien n'est poussé : « La branche forceupdate/dependencies a
  changé sur la forge pendant l'envoi : rien n'est poussé. Relancer. »
- **Jamais par-dessus le commit d'un autre.** Un commit de la branche qui n'a pas la marque
  `Generated-by: forceupdate` (une correction poussée à la main pour une majeure) bloque
  l'envoi : « La branche forceupdate/dependencies a un commit qui ne vient pas de forceupdate
  (…) : rien n'est poussé, pour ne pas l'écraser. L'intégrer à la branche par défaut, ou
  supprimer la branche, puis relancer. » Une fusion de la branche par défaut (« Update
  branch » de GitHub) est tolérée.
- **Même contenu, rien n'est poussé** : seule la description est refaite. Le résultat dit
  « PR #41 mise à jour : elle avait déjà ces changements, rien n'est poussé, sa description
  est refaite ».

### Le commit

- Il contient les manifestes réécrits et les lockfiles régénérés (et le `vendor/` refait),
  nommés un par un. Jamais les fichiers qu'un outil en échec a remis comme avant, ni ce
  qu'un outil a laissé à côté (un `.venv`). Une majeure que l'outil refuse est retirée et le
  reste part (voir « Sur un échec » dans USAGE.md).
- Il est fait au nom du compte du token : son nom (sinon son identifiant), et son adresse
  `noreply`, qui rattache le commit au compte sans dévoiler la vraie :

  | Forge | Adresse du commit |
  |---|---|
  | GitHub | `<id>+<identifiant>@users.noreply.github.com` |
  | GitLab | `<id>-<identifiant>@users.noreply.<hôte>` |
  | Bitbucket | l'adresse principale et confirmée du compte : Bitbucket n'a pas d'adresse `noreply` |

  Sur Bitbucket, c'est par cette adresse qu'un commit se rattache au compte. Si le token ne
  permet pas de la lire, les commits ne seront pas rattachés au compte (la carte le dit pour
  un compte connecté par OAuth).
- Son message :

  ```
  Mise à jour des dépendances

  - lodash 4.17.20 → 4.18.1

  Generated-by: forceupdate 1.0.0
  ```

  Seules les versions que le lockfile a atteintes y sont : ni une majeure retirée, ni une
  version retenue en dessous (la description les dit).

- Rien à commiter au bout du compte (aucun fichier changé) : rien n'est poussé, « rien à
  faire sur la branche par défaut telle qu'elle est ». Si c'est parce que l'outil de lockfile a
  gardé les versions (une dépendance indirecte que le paquet qui la tire ne laisse pas monter :
  voir [La régénération](USAGE.md#ce-qui-vaut-pour-tous) dans USAGE.md), le résultat le dit
  : « aucune mise à jour n'a pu se faire : d'autres paquets retiennent les versions choisies ;
  rien n'est poussé », puis chaque paquet, « minimatch 10.2.6, pas 11.0.1 (backend) : retenue
  par nodemon 3.1.14 », et quoi faire (monter ce paquet, ou forcer sa version). Dans une PR qui
  part, une version retenue est dite de même, dans la description (« retenue en … par … »,
  avec la version de ce paquet qui l'accepterait : « (nodemon 4.0.1 l'accepte) »). Au
  récapitulatif, avant l'envoi, une version que d'autres paquets retiendront ou feront refuser est
  déjà dite (« retenue par nodemon 3.1.14 : monter d'abord nodemon en 4.0.1 », « refusée à cause
  de arq 0.28.0 : aucune de ses versions ne l'accepte »).

### La description

Titre : « Mise à jour des dépendances (forceupdate) ». La description, en français :

- la version de forceupdate, le commit et la branche de départ ;
- « Mises à jour » : un tableau (paquet, projet, version, failles corrigées, état : « faite »,
  « faite, en … » si l'outil a pris plus haut, « retenue en … par … (… l'accepte) », « lockfile à régénérer
  (npm absent) », « pas faite : uv la refuse (Because arq==0.28.0 depends on redis<6…) » pour
  une majeure retirée, « pas faite : lockfile en échec ») ;
- « Lockfiles » : régénéré par quel outil et relu par quoi (tout `package-lock.json` est relu
  par `npm ci --dry-run`, et refait par une vraie installation si npm le refuse : voir « Le npm
  du projet » dans USAGE.md), « régénéré sans redis 8.1.0, qu'il refuse », ce que l'outil a dit
  en plus, la commande à lancer, l'erreur de l'outil. Sans les chemins de l'ordinateur : le
  dossier du clone devient `.`, le dossier personnel `~` ;
- « Non appliquées » : les options sautées, et pourquoi ;
- « Rapport de l'analyse » : le rapport Markdown du dépôt, raccourci au-delà de 60 000
  caractères (GitHub refuse une description de plus de 65 536) ;
- une dernière ligne : relancer met à jour cette PR, et un commit ajouté à la main l'en
  empêche.

### Un lockfile dont l'outil manque

L'outil d'un lockfile (npm, uv, cargo…) n'est pas sur l'ordinateur : le récapitulatif le
dit (« npm absent » : « npm n'est pas installé sur cet ordinateur : les manifestes seront
réécrits, et la description de la PR donnera la commande à lancer »). Les manifestes partent
quand même. La description dit : « pas régénéré, npm n'est pas installé là où cette PR a été
préparée. À lancer dans `<dossier>`, puis commiter », et la commande.

Un outil qui échoue : ses fichiers sont remis comme avant et ne sont pas dans la PR ; la
description donne son erreur. S'il échouait à cause d'une majeure, elle seule est retirée, le
reste part : le résultat de l'envoi le dit (« typescript 7.0.2 (frontend) : pas faite, l'outil
de frontend/package-lock.json la refuse : … »), avec ce qui s'est passé en route sur un
lockfile (« npm refusait le lockfile qu'il venait d'écrire … refait par … »).

### Il faut git

L'envoi clone et pousse par git. Sans git : « git n'est pas installé : il faut git pour
cloner. », et rien ne part.

### Relancer

Relancer (depuis « Mes dépôts », ou depuis le rapport du dépôt) met à jour **la même PR** :
la branche est refaite sur la branche par défaut du moment, la description aussi. Jamais une
deuxième PR, même si une autre fenêtre l'a ouverte entre-temps.

Un dépôt sauté parce que rien n'y est coché (« aucune mise à jour cochée » : la PR d'avant est
fusionnée, il ne reste que des majeures, jamais pré-cochées) a un lien « choisir les mises à
jour », qui mène au choix de ses mises à jour pour ce récapitulatif.

Une PR de forceupdate fusionnée n'est jamais mise à jour : la suivante en ouvre une nouvelle (#2).

Un dépôt en échec (la forge ne répondait pas, un token refusé puis reconnecté) se renvoie depuis
le résultat : « Renvoyer le dépôt en échec » repart avec la même sélection, sans repasser par le
récapitulatif ; les dépôts déjà envoyés ne bougent pas. Le titre du résultat dit l'échec (son
icône : rouge si tout a échoué, avertissement si une partie), et l'erreur de git écrit le dossier
personnel `~`.

### Une PR fermée sans fusion

Si la dernière PR de forceupdate d'un dépôt (de `forceupdate/dependencies` vers la branche
par défaut) a été fermée sans être fusionnée, et qu'aucune n'est ouverte, le récapitulatif
le signale : le badge « PR #3 fermée sans fusion », la phrase « La PR #3 a été fermée sans
fusion le 30 oct. 2026 : l'envoyer en ouvre une nouvelle. Pas cochée par défaut. », et le
lien « Voir la PR #3 sur GitHub ». Le dépôt est prêt, mais pas coché.

Cocher et envoyer ouvre une nouvelle PR. La branche, restée sur la forge, est reprise : à
contenu égal, rien n'est poussé. Une PR fusionnée, ou une PR ouverte depuis, et plus rien
n'est signalé. Rien n'est gardé sur l'ordinateur : la forge sert de mémoire.

### Ctrl+C pendant un envoi

Arrêter `forceupdate ui` (Ctrl+C) pendant un envoi l'arrête aussitôt : l'outil de lockfile
et la commande git en cours sont tués, les dépôts qui restent ne partent pas. La console le
dit : « envoi des PR en cours : interrompu. Le relancer depuis l'interface ; une branche
déjà poussée sans sa PR sera reprise. » Un dépôt en cours échoue avec « Interrompu :
forceupdate s'est arrêté. Relancer l'envoi ; une branche déjà poussée sera reprise. »

Un push tué en route a poussé, ou pas : la forge change la branche d'un coup. Relancer
l'envoi reprend une branche poussée sans sa PR, et ouvre la PR. Les analyses qui clonent
s'arrêtent de même.

## git et sa configuration

- **Le token** passe à git par un *credential helper* éphémère, qui le lit dans
  l'environnement du seul processus git. Il ne le donne qu'en `https`, et qu'à l'hôte de
  l'adresse du dépôt (port compris, pour une instance). Les *credential helpers* de la
  personne sont écartés pour ces commandes : rien n'est gardé dans le Gestionnaire
  d'identification de Windows. L'adresse du dépôt est construite par forceupdate, sans
  identifiants : rien dans `.git/config`.
- **Nom présenté avec le token** : `x-access-token` (GitHub), `oauth2` (GitLab),
  `x-token-auth` (Bitbucket, OAuth), `x-bitbucket-api-token-auth` (Bitbucket, token d'API).
- **`url.<base>.insteadOf`** de la configuration git (GitHub par SSH :
  `url."git@github.com:".insteadOf https://github.com/`) est ignoré pour les commandes de
  forceupdate, `pushInsteadOf` aussi : elles passent par HTTPS avec le token. Seule une règle
  sur l'adresse exacte d'un dépôt l'emporte : git va alors ailleurs, sans le token, et
  échoue (« la forge refuse le token », ou ce que git a dit). La retirer, ou la faire porter
  sur un début d'adresse.
- **Gardé** de la configuration de la personne : le proxy, les certificats
  (`http.sslbackend`…).
- **Imposé**, parce que ça changerait le résultat : pas de conversion des fins de ligne
  (`core.autocrlf=false`), les chemins longs sous Windows, aucun hook, pas de signature des
  commits, aucune question dans le terminal. Le clone est superficiel (`--depth 1`), d'une
  seule branche, sans étiquettes, sans sous-modules, sans télécharger les fichiers LFS.
- **Délai** : 600 secondes par clone, `fetch` ou push. L'écran Réglages le change (« Délai
  d'un clone ou d'un push », clé `clone-timeout` de `forceupdate.toml`).
- **Erreurs** : git est lu en anglais, puis dit en français : « la forge refuse le token »,
  « le token n'a pas le droit d'écrire dans ce dépôt », « la branche est protégée, ou une
  règle du dépôt refuse le push », « la forge ne répond pas (réseau, DNS, certificat) »,
  avec les dernières lignes de git, sans le token.

## Le dossier de travail du serveur

Tout ce que le serveur range est dans un seul dossier, `forceupdate-ui-*`, dans le dossier
temporaire du système (`%TEMP%` sous Windows) :

- `depot-*` : les fichiers téléchargés d'un dépôt analysé, et son clone s'il a fallu cloner ;
- `envoi-*` : un fichier déposé dans le navigateur ;
- `pr-*` : le clone d'un envoi, effacé à la fin du dépôt.

Le dossier est verrouillé tant que le serveur tourne, et effacé à l'arrêt. Un arrêt brutal
(processus tué, ordinateur éteint) le laisse : le démarrage suivant l'efface, en tâche de
fond. Un fichier encore ouvert (par un git orphelin) le garde pour le démarrage d'après.
Jamais le dossier d'un autre `forceupdate ui` qui tourne.

## Limites

**GitHub**

- `github.com` seulement : pas de GitHub Enterprise Server.
- La page d'autorisation ne marche que par l'adresse `127.0.0.1` (pas `localhost`, ni le
  serveur de développement du front).

**GitLab**

- Une instance sous un chemin (`https://exemple.org/gitlab`) n'est pas prise.
- Pas d'OAuth sur une instance : un token seulement. Un token personnel qui expire n'est pas
  renouvelé (son échéance est dite sur la carte).
- Les langages d'un projet sont pesés en nombre de fichiers (GitLab ne donne pas les
  tailles).
- Les requêtes restantes sont celles de la dernière réponse, par minute, parfois d'un seul
  point d'API.
- Un fork d'un projet que le compte ne voit pas n'est pas toujours marqué fork.

**Bitbucket**

- Bitbucket Data Center (auto-hébergé) : hors V1.
- Pas de révocation par l'API : retirer l'accès dans
  `https://bitbucket.org/account/settings/app-authorizations/`.
- Pas d'adresse `noreply` : les commits portent l'adresse principale du compte.
- Les droits d'un token d'API Atlassian ne se vérifient pas.
- Un dépôt où le compte n'écrit que par un groupe : forceupdate se fie à la permission que
  donne Bitbucket, la permission effective d'après sa documentation. Pas vérifié en vrai :
  un tel dépôt pourrait être vu en lecture seule.
- Les « access tokens » de dépôt ou de workspace (Bitbucket Premium) ne sont pas pris.
- Les requêtes restantes ne se savent pas.
- Une arborescence de plus de 12 niveaux de dossiers ou de 10 000 entrées est clonée.
- Selon un fil de la communauté d'Atlassian, la page d'autorisation reviendrait à chaque
  connexion (pas constaté).

**Les PR**

- Un envoi ne s'annule pas depuis l'interface (Ctrl+C l'arrête).
- Les récapitulatifs ne survivent pas au serveur : un envoi interrompu ne se voit qu'à la
  console.
- Une PR fermée sans fusion n'est signalée que si c'est la dernière de la branche, et que la
  forge répond.
- Un commit fait à la main sur `forceupdate/dependencies` bloque les envois suivants,
  jusqu'à ce qu'il soit fusionné ou la branche supprimée.
- La description est en français.
- Une règle `insteadOf` de la personne sur l'adresse exacte d'un dépôt fait échouer l'envoi.

**Le reste**

- Un sous-module n'est pas analysé : l'analyser comme un dépôt à part.
- Un dépôt vidé entre la liste et l'analyse sort « non concluant » (« Dépôt vide »).
- Le dossier de travail d'un arrêt brutal reste jusqu'au démarrage suivant.
- Sous Linux sans Secret Service, aucun compte ne se connecte sans un autre trousseau.
