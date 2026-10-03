# TextoForHA

Add-on Home Assistant avec une interface commune pour plusieurs modems : SMS,
réseau, configuration, contacts et SIM selon les capacités du matériel.

**Version 0.1.1 bêta.** L’objectif est une diffusion communautaire. La compatibilité
n’est pas universelle : le mode HiLink et les commandes AT varient selon le firmware.

Pour une installation courte, consulter [Démarrage rapide](../QUICKSTART.md).

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

Copier le dossier `textoforha` dans `/addons/textoforha`, recharger la boutique des
add-ons, installer **TextoForHA**, puis démarrer et ouvrir l’interface web.
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
TextoForHA ne scanne pas les ports pour y envoyer des commandes.

## Options de l’add-on

- `poll_interval` : de 15 à 300 secondes, 60 par défaut ;
- `import_existing` : import initial des intégrations connues, sans effet si la
  configuration persistante existe déjà.

Les actions d’envoi et PIN ne sont jamais réessayées par l’application. Après une
réponse incertaine, vérifier le résultat avant de renouveler l’opération. Une réponse
positive d’envoi signifie que le modem a accepté le SMS, pas que le destinataire l’a reçu.

## Envoi depuis une automation Home Assistant

Si la clé est gérée par les intégrations existantes, il est préférable d’appeler
directement leur service, sans passer par l’interface TextoForHA :

```yaml
action: huawei_sms.send
data:
  phone_number: "+33612345678"
  message: "Alerte : la maison est sans courant."
```

Pour Qualcomm, appeler `qualcomm_sms.send` avec en plus l’`entry_id` de
l’intégration. TextoForHA réutilise déjà ces mêmes services lorsque la connexion
« intégration existante » est choisie.

Pour une clé configurée directement dans TextoForHA (HiLink ou port AT), Home
Assistant peut appeler l’API interne de l’add-on au moyen d’un `rest_command`.
Ajouter ceci à `configuration.yaml` en remplaçant `local_textoforha` par le nom
réseau de l’add-on et `modem_id` par l’identifiant configuré dans TextoForHA :

```yaml
rest_command:
  textoforha_send_sms:
    url: "http://local_textoforha:8099/api/modems/{{ modem_id }}/actions/send"
    method: POST
    headers:
      Content-Type: application/json
      X-TextoForHA: "1"
    payload: >-
      {"phone_number": {{ phone_number | to_json }},
       "message": {{ message | to_json }}}
```

Puis, dans une automation :

```yaml
action: rest_command.textoforha_send_sms
data:
  modem_id: modem_at
  phone_number: "+33612345678"
  message: "Alerte : la maison est sans courant."
```

L’API reste limitée au réseau interne de Home Assistant et exige l’en-tête
`X-TextoForHA`; elle n’est pas destinée à être publiée vers Internet. Tester la
commande depuis **Outils de développement > Actions** avant de l’employer dans
une alerte. Avec un modem AT, rester à un SMS simple et court (160 caractères
GSM7 ou 70 UCS2), sans emoji hors BMP.

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
.venv/bin/pip install -r textoforha/requirements.txt pytest ruff playwright
.venv/bin/pytest -q
.venv/bin/ruff check .
cd textoforha
TEXTOFORHA_DEV=1 TEXTOFORHA_DATA=/tmp/textoforha-demo TEXTOFORHA_PORT=8108 ../.venv/bin/python -m app.server
```

Le mode de développement écoute uniquement
sur localhost ; ne pas l’activer dans l’add-on installé.

Tests navigateur, depuis la racine, avec l’application de développement sur le port 8108 :

```sh
.venv/bin/playwright install --with-deps chromium
TEXTOFORHA_TEST_URL=http://127.0.0.1:8108 .venv/bin/python tests/browser_checks.py
```

Les requêtes API de ces tests navigateur sont entièrement interceptées : les envois
et suppressions sont simulés. Aucun SMS réel n’est envoyé par la suite de tests.

Le pilote AT provient du composant compagnon HiLink2HA, sous la même licence MIT.
