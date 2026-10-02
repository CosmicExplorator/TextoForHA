# Validation de la bêta 0.1.0

- 37 tests Python réussis et vérification Ruff réussie.
- Tests navigateur réussis : vues communes, sélection du modem, brouillons, protection contre les injections HTML, affichage mobile et routage des actions.
- Les envois, suppressions et opérations PIN ont été testés avec des simulations : aucun SMS réel envoyé pour la validation.
- Image amd64 construite et add-on démarré sur HAOS.
- Les deux intégrations existantes sont importées en mode compatibilité. Qualcomm disponible ; Huawei indisponible car débranchée.
- Les 17 fichiers de l’intégration Huawei originale sont inchangés.
- Le workflow prévoit aussi une construction aarch64, non exécutée dans cette session.
- L’ouverture Ingress dans une session utilisateur Home Assistant reste à vérifier : le jeton technique ne permet pas de créer cette session.
- Les pilotes directs nécessitent des essais matériels supplémentaires avant une diffusion stable. La compatibilité avec toutes les clés Qualcomm ou Huawei n’est pas garantie.

L’add-on est une bêta. Les sources sont préparées pour publication, mais aucun dépôt public n’a été publié dans cette session.
