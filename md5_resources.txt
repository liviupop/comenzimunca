
Copiat de aici:
https://apple.stackexchange.com/questions/30507/md5-checksum-on-multiple-file

The md5 command will check multiple files for you. Simply list all the files you want after the command. I.e. md5 md1.gz md2.gz md3.gz. It will output the md5 hashes like so:

MD5 (md1.gz) = 1c2c02b085a1bc2fed683eca86c0df02
MD5 (md1.gz) = c5515451d8f90a822457a4a8e4bf1791
If you want just the hashes, use the -q flag, it will print only the hash, without the identifying information.

I'm guessing that you want to compare the hash of the files against that in the corresponding .md5 file. You could write a quick shell script to check each generated hash against the one stored in the .md5 file.

Something like this should work:

#!/bin/bash

for file in "$@"; do
  generatedhash=$(md5 -q "$file")
  storedhash=$(< "$file".md5)
  if [[ $generatedhash != $storedhash ]]; then
    echo "Hash for file '$file 'does not match"
  fi
done

Save that to a text file, call it something like checkmd5.sh and do chmod +x checkmd5.sh in the terminal.

It will print out a warning for all files that don't have a matching hash. It prints nothing if the hashes do match. It's quick and dirty, so apologies if it doesn't work for your particular case. But based on the examples you gave, if you run ./checkmd5.sh md*.gz it should check the hashes of the .gz files against the corresponding .md5 files and tell you if any are bad.

----

