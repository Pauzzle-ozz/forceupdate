"""L'interface web : un serveur local (FastAPI, uvicorn) qui pilote le moteur par HTTP, depuis
le navigateur de la personne (brief, décision n°10).

- ``app.py`` : l'application, et ``serve`` pour ``forceupdate ui`` ;
- ``security.py`` : jeton de session, ``Host``, ``Origin``, en-têtes ;
- ``jobs.py`` : les analyses et les mises à jour, en tâches de fond hors de la boucle du
  serveur, et leur progression ;
- ``sse.py`` : la progression envoyée au navigateur (Server-Sent Events) ;
- ``routes/`` : les routes de ``/api`` ;
- ``schemas.py`` : ce que l'API reçoit et rend ; ``openapi.py`` : le schéma exporté dans
  ``openapi.json``, d'où viennent les types du front ;
- ``static/`` : le front construit (E14).

Pas de logique métier ici : comme ``cli.py``, tout passe par le moteur et ``update/``.
"""

from forceupdate.web.app import Settings, create_app, serve

__all__ = ["Settings", "create_app", "serve"]
