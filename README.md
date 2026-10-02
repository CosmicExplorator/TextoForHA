# Dongle Link

Add-on Home Assistant avec une interface commune pour plusieurs modems : SMS,
réseau, configuration, contacts et SIM selon les capacités du matériel.

**Version 0.1.0 bêta.** L’objectif est une diffusion communautaire. La compatibilité
n’est pas universelle : le mode HiLink et les commandes AT varient selon le firmware.

## Trois connexions possibles

| Connexion | Usage | SMS | Réseau | Contacts et PIN |
| --- | --- | --- | --- | --- |
| Huawei HiLink directe | Modem accessible par HTTP(S) | Lire, envoyer, supprimer | Lecture selon firmware | Selon firmware |
| Port série AT | Port de commande AT déjà identifié | Lire, envoyer un SMS simple, supprimer | SIM, CSQ, CREG | Lecture SIM uniquement |
| Intégration Home Assistant existante | Réutilise `huawei_sms` ou `qualcomm_sms` | Selon intégration | Capteurs existants | Selon intégration |

Les actions visent toujours la clé sélectionnée. Il n’y a ni envoi en lot,
ni suppression globale, ni réponse automatique. Les SMS ne sont pas archivés dans
une base de données supplémentaire ; l’add-on garde seulement le dernier état en mémoire.
La lecture peut marquer les SMS comme lus sur le modem.

## Installation locale

Copier le dossier `dongle_link` dans `/addons/dongle_link`, recharger la boutique des
add-ons, installer **Dongle Link**, puis démarrer et ouvrir l’interface web.
Aucun port externe n’est publié : l’accès passe par Home Assistant Ingress.
Les plateformes déclarées sont amd64 et aarch64 ; le workflow vérifie la construction
des deux images. Une construction réussie ne garantit pas tous les modèles de modem.

Pour une distribution communautaire, publier ce dépôt sur GitHub puis ajouter son
URL comme dépôt d’add-ons dans Home Assistant. Aucune URL publique n’est présumée
créée par les fichiers de ce projet. L’installation construit l’image localement.

## Première utilisation

Au premier démarrage, `import_existing: true` importe les deux capteurs connus
`sensor.sms_huawei_e3372` et `sensor.qualcomm_sms_sms` s’ils existent. Ces entrées
utilisent les intégrations existantes : leurs ports et réglages restent gérés par
Home Assistant. Les noms d’entités personnalisés peuvent être configurés manuellement.

Sinon, cliquer sur **Ajouter une clé** :

- HiLink : adresse du modem et identifiants éventuels ;
- AT : chemin `/dev/serial/by-id/...` du port AT, vitesse et mémoire SMS ;
- intégration existante : type, capteur SMS et préfixe des capteurs réseau.

Les clés sont configurées dans l’application et persistées dans `/data/modems.json`.
Ce fichier est privé (0600) et inclus dans les sauvegardes de l’add-on. Le mot de passe
reste côté serveur ; un champ vide lors d’une modification conserve la valeur actuelle.

**Un seul logiciel doit piloter un port AT.** Pour passer d’une intégration existante
à une connexion série directe, désactiver d’abord l’intégration correspondante et
fermer microcom. Ne jamais sélectionner un dongle Zigbee/Z-Wave comme port AT.
Dongle Link ne scanne pas les ports pour y envoyer des commandes.

## Options de l’add-on

- `poll_interval` : de 15 à 300 secondes, 60 par défaut ;
- `import_existing` : import initial des intégrations connues, sans effet si la
  configuration persistante existe déjà.

Les actions d’envoi et PIN ne sont jamais réessayées par l’application. Après une
réponse incertaine, vérifier le résultat avant de renouveler l’opération. Une réponse
positive d’envoi signifie que le modem a accepté le SMS, pas que le destinataire l’a reçu.

## Limites de la bêta

- AT : un seul segment sortant ; jusqu’à 160 caractères GSM7 (certains comptent
  double) ou 70 caractères UCS2 ; emojis hors BMP exclus à l’envoi.
- Les SMS multiparties reçus sont présentés segment par segment ; Unicode et emojis
  reçus sont normalisés pour l’affichage.
- Le réseau est en lecture seule : pas de changement APN, bandes, mode radio ni de
  routage de connexion Internet.
- La gestion du PIN et des contacts dépend du firmware Huawei ; elle n’est pas
  annoncée pour le pilote AT.
- Le pont vers `huawei_sms` ne permet qu’une seule entrée Huawei, conformément à
  l’intégration historique. Plusieurs Huawei sont possibles en connexion directe.
- Ce projet ne crée pas automatiquement de nouvelles entités MQTT ou HA. Le mode
  de compatibilité conserve les entités déjà présentes.

## Développement et tests

```sh
python -m venv .venv
.venv/bin/pip install -r dongle_link/requirements.txt pytest ruff playwright
.venv/bin/pytest -q
.venv/bin/ruff check .
cd dongle_link
DONGLE_LINK_DEV=1 DONGLE_LINK_DATA=/tmp/dongle-link-demo DONGLE_LINK_PORT=8108 ../.venv/bin/python -m app.server
```

Le mode de développement écoute uniquement
sur localhost ; ne pas l’activer dans l’add-on installé.

Tests navigateur, depuis la racine, avec l’application de développement sur le port 8108 :

```sh
.venv/bin/playwright install --with-deps chromium
DONGLE_LINK_TEST_URL=http://127.0.0.1:8108 .venv/bin/python tests/browser_checks.py
```

Les requêtes API de ces tests navigateur sont entièrement interceptées : les envois
et suppressions sont simulés. Aucun SMS réel n’est envoyé par la suite de tests.

Le pilote AT provient du composant compagnon HiLink2HA, sous la même licence MIT.
