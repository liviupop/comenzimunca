# comenzimunca
Comenzi Terminal munca

#Comandă extragere semnătură MD5 dintr-un director - recurent 
find * -iname '*.tif' -exec md5  '{}' \;  > md5_hash_Nume_Cont_Fond_scanat.txt


#Comandă extragere semnătură SHA1 dintr-un director - recurent 
find * -iname '*.tif' -exec openssl sha1  '{}' \;  > sha1_hash_Nume_Cont_Fond_scanat.txt

#Cauta fisiere în toate conturile după extensie
sudo find /Users -name *.pdf > results.txt

