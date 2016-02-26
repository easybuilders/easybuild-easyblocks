##
# Copyright 2009-2016 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://vscentrum.be/nl/en),
# Flemish Research Foundation (FWO) (http://www.fwo.be/en)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# http://github.com/hpcugent/easybuild
#
# EasyBuild is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation v2.
#
# EasyBuild is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with EasyBuild.  If not, see <http://www.gnu.org/licenses/>.
##
"""
EasyBuild support for building and installing xml R, implemented as an easyblock

@author: Kenneth Hoste (Ghent University)
@author: Balazs Hajgato (Free University Brussels - VUB)
"""
from easybuild.framework.easyconfig import CUSTOM
from easybuild.easyblocks.generic.configuremake import ConfigureMake

class EB_Xorg(ConfigureMake):
    """Support for building/installing Xorg related files into a common prefixdir ."""

    @staticmethod
    def extra_options():
        """Custom easyconfig parameters for Xorg."""

        extra_vars = {
            #Xorg_installs[(name, version, configuredir(def:name-version), extension(def:.tar.bz2),
            #               extra_source_urls(def:do not add),...]
            'Xorg_installs': [[], "Extra native libraries to install (list of tuples)", CUSTOM],
        }

        return ConfigureMake.extra_options(extra_vars)

    def run_all_steps(self, *args, **kwargs):

        #Xorg_installs[(name, version, configuredir(def:name-version), extension(def:.tar.bz2),
        #               extra_source_urls(def:do not add),...]
        add_sources = []
        add_preconfigopts = []
        add_source_urls = []
        xtmp = 'Xorg.tmp'
        extension = '.tar.bz2'
        for tup in self.cfg['Xorg_installs']:
            tuplen = len(tup)
            if tuplen < 2:
                 self.log.info("Not enough parameters for %s" % tup[0])

            # tweak preconfigopts to cd into different directories listed in installs[]
            if tuplen > 2:
                add_preconfigopts += ['find . -maxdepth 0 -type l -exec rm {} \; && ln -s %s %s && cd %s &&' % (tup[2], xtmp, xtmp)]
            else:
                add_preconfigopts += ['find . -maxdepth 0 -type l -exec rm {} \; && ln -s %s-%s %s && cd %s &&' % (tup[0], tup[1], xtmp, xtmp)]

            # tweak sources to download all sources downloaded in installs[]
            if tuplen > 3:
                add_sources += ['%s-%s%s' % (tup[0], tup[1], tup[3])] 
            else:
                add_sources += ['%s-%s%s' % (tup[0], tup[1], extension)] 

            # add extra soure_urls
            if tuplen > 4:
                add_source_urls += ['%s' % tup[4]] 
           
        # set start_dir to workdir
        self.cfg['start_dir'] = '..'
        # tweak preconfigopts make a link to workdir
        self.cfg['preconfigopts'] = add_preconfigopts
        self.cfg['prebuildopts'] = 'cd %s &&' % xtmp
        self.cfg['preinstallopts'] = 'cd %s &&' % xtmp
        self.log.info("The following preconfigoptions were added :%s" % add_preconfigopts)
        # tweak sources to download all sources 
        self.cfg['sources'] = add_sources
        self.log.info("The following sources were added :%s" % add_sources)
        # add extra soure_urls
        self.cfg['source_urls'] = self.cfg['source_urls'] + add_source_urls
        self.log.info("The following source_urls were added :%s" % add_source_urls)
       
        super(EB_Xorg, self).run_all_steps(*args, **kwargs)
