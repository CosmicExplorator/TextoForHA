# TextoForHA

Addon Home Assistant pour **lire, envoyer et gérer les SMS** de tes modems.

## 🔌 Modems supportés
- **Huawei HiLink** (B535, B818, E3372, etc.)
- **Modems série (AT)** (Qualcomm, Wavecom, etc.)

## ✨ Fonctionnalités
- Lire / envoyer / supprimer des SMS
- Voir l'état du réseau (signal, opérateur, type de connexion)
- Interface web sur **`http://[HA_IP]:8099`**
- Compatible avec les intégrations existantes (HiLink2HA)

## 📝 Configuration

### Exemple pour Huawei HiLink
```yaml
modem_type: huawei
host: 192.168.1.100
username: admin
password: ton_mot_de_passe
poll_interval: 60
```

### Exemple pour modem série (AT)
```yaml
modem_type: at
port: /dev/ttyUSB0
baudrate: 115200
```

## ⚠️ Limitations
- Certaines clés Huawei ont des **firmwares verrouillés** (les SMS ne seront pas accessibles).
- Les SMS longs (> 160 caractères) peuvent être coupés en plusieurs parties.

## 🚀 Installation
1. Ajoute ce dépôt dans **HACS** ou copie le dossier `textoforha` dans `/config/addons/`.
2. Redémarre Home Assistant.
3. Installe l'addon dans **Paramètres > Addons > Boutique des addons**.
4. Configure les options et lance-le.
