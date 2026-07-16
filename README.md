# comenzimunca
Comenzi Terminal munca

**[wp4-rescue/](wp4-rescue/)** — EU Project Distress Detector: găsește proiecte EU finanțate cu livrabile digitale promise și semne de nelivrare (vezi `wp4-rescue/README.md`). Dashboard-ul se deployează pe Cloudflare Workers din `wp4-rescue/site/` (config: `wrangler.jsonc`).

#Comandă extragere semnătură MD5 dintr-un director - recurent 
find * -iname '*.tif' -exec md5  '{}' \;  > md5_hash_Nume_Cont_Fond_scanat.txt


#Comandă extragere semnătură SHA1 dintr-un director - recurent 
find * -iname '*.tif' -exec openssl sha1  '{}' \;  > sha1_hash_Nume_Cont_Fond_scanat.txt

#Cauta fisiere în toate conturile după extensie
sudo find /Users -name *.pdf > results.txt

