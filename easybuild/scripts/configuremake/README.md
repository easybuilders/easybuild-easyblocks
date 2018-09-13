The script here is intended to be used by the configuremake generic easyblock. It is an update for `config.guess` used
by `Autotools` which is frequently not up to date in package releases.

You can obtain the newest version of `config.guess` and `config.sub` from the 'config' project at
http://savannah.gnu.org/ . The commands to fetch them are
```
$ wget -O config.guess 'http://git.savannah.gnu.org/gitweb/?p=config.git;a=blob_plain;f=config.guess;hb=HEAD'
```