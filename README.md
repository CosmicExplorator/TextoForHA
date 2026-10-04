# TextoForHA

Add-on Home Assistant pour gérer les SMS et l’état réseau de plusieurs modems.

**Version 2026-10.2 bêta.** L’objectif est une diffusion communautaire. La compatibilité
n’est pas universelle : le mode HiLink et les commandes AT varient selon le firmware.

Pour une installation courte, consulter [Démarrage rapide](QUICKSTART.md).

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

1. Démarrer l’add-on.
2. Ouvrir TextoForHA.
3. Cliquer sur **Ajouter une clé**.
4. Choisir un mode :
   - **HiLink** : URL du modem et identifiants éventuels.
   - **AT** : port `/dev/serial/by-id/...`, vitesse et mémoire SMS.
   - **Intégration existante** : capteur SMS et préfixe réseau.
5. Vérifier que le modem est **Disponible**.

Les modems sont enregistrés dans `/data/modems.json`. Ce fichier est privé et inclus
dans les sauvegardes. Un mot de passe vide conserve le mot de passe déjà enregistré.

> Un seul logiciel doit utiliser un port AT. Désactiver toute autre intégration qui
> utilise ce port. Ne jamais choisir un dongle Zigbee ou Z-Wave.

## Options de l’add-on

- `poll_interval` : de 15 à 300 secondes, 60 par défaut ;
- `import_existing` : import initial des intégrations connues, sans effet si la
  configuration persistante existe déjà.

Les actions d’envoi et PIN ne sont jamais réessayées par l’application. Après une
réponse incertaine, vérifier le résultat avant de renouveler l’opération. Une réponse
positive d’envoi signifie que le modem a accepté le SMS, pas que le destinataire l’a reçu.

## Automatisations

1. Définir le **Modem par défaut** dans les options de l’add-on.
2. Appeler `POST /api/actions/send` depuis Home Assistant.
3. Envoyer `phone_number` et `message` en JSON.
4. Tester l’envoi avant d’activer une alerte.

L’API reste sur le réseau interne Home Assistant. Ne pas publier son port sur Internet.
Avec un modem AT, rester sous 160 caractères GSM ou 70 caractères Unicode.

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
.venv/bin/pip install -r textoforha/requirements.txt pytest httpx2 ruff playwright
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
