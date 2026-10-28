"""La mise à jour : des constats aux fichiers réécrits.

- ``constraints.py`` : réécrire une contrainte pour une nouvelle version, dans son style ;
- ``planner.py`` : les mises à jour possibles de chaque paquet, et la sélection ;
- ``writers/`` : réécrire les contraintes choisies dans les manifestes, avec leur diff ;
- ``lockfiles.py`` : régénérer ensuite les lockfiles, avec l'outil de chacun ;
- ``git.py`` : le garde-fou, les fichiers qui ont des changements que git n'a pas en commit ;
- ``local.py`` : tout cela enchaîné sur une source locale, pour ``forceupdate update`` et l'API.
"""
