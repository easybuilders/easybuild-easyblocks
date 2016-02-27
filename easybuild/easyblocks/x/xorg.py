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
EasyBuild support for building and installing Xorg related material into one destination, implemented as an easyblock

@author: Kenneth Hoste (Ghent University)
@author: Balazs Hajgato (Free University Brussels - VUB)
"""
import os
from easybuild.framework.easyblock import EasyBlock
from easybuild.tools.build_log import EasyBuildError
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.run import run_cmd

class EB_Xorg(EasyBlock):
    """Support for building/installing Xorg related files into a common prefixdir ."""

    @staticmethod
    def extra_options():
        """Custom easyconfig parameters for Xorg."""

        extra_vars = {
            #Xorg_installs[(name, version, {'extension': '.tar.bz2',  
            #                               'extra_source':  '%s-%s' % (name, version),
            #                               'extra_source_urls': '',
            #                               'extra_start_dir': '%s-%s' % (name, version)}), ...]
            'Xorg_installs': [[], "Extra native libraries to install (list of tuples)", CUSTOM],
        }

        return EasyBlock.extra_options(extra_vars)

    def run_all_steps(self, *args, **kwargs):

        #Xorg_installs[(name, version, configuredir(def:name-version), extension(def:.tar.bz2),
        #               extra_source_urls(def:do not add),...]
        add_sources = []
        add_source_urls = []
        default_extension = '.tar.bz2'
        xtmp = 'Xorg.tmp'
        for tup in self.cfg['Xorg_installs']:
            tuplen = len(tup)
            if tuplen < 2:
                 raise EasyBuildError("Not enough parameters for: %s", tup[0])

            # tweak package related options
            if tuplen == 2:
                add_sources += ['%s-%s%s' % (tup[0], tup[1], default_extension)] 
            if tuplen > 3:
                extra_param = tup[2]
                # sources
                if 'extension' in extra_param:
                    dl_extension = extra_param['extension'] 
                else:
                    dl_extension = default_extension 
                if 'extra_source' in extra_param:
                    add_sources += ['%s%s' % (extra_param['extra_source'], dl_extension)] 
                else:
                    add_sources += ['%s-%s%s' % (tup[0], tup[1], dl_extension)] 
                # source_urls
                if 'extra_source_urls' in extra_param: 
                    add_source_urls += extra_param['extra_source_urls']

        # tweak sources to download all sources 
        self.cfg['sources'] = add_sources
        self.log.info("The following sources were added :%s" % add_sources)
        # add extra soure_urls
        self.cfg['source_urls'] = self.cfg['source_urls'] + add_source_urls
        self.log.info("The following source_urls were added :%s" % add_source_urls)
       
        super(EB_Xorg, self).run_all_steps(*args, **kwargs)

    def configure_step(self):
        """ Configure step for Xorg """

        for tup in self.cfg['Xorg_installs']:
            tuplen = len(tup)
            if tuplen < 2:
                 raise EasyBuildError("Not enough parameters for: %s", tup[0])

            xorg_subdir = '%s-%s' % (tup[0], tup[1]) 
            preconfigopts = ''
            cmd_prefix = ''
            prefix_opt = '--prefix='
            c_installdir = self.installdir
            configopts = ''
            if tuplen > 3:
                extra_param = tup[2]
                if 'extra_start_dir' in extra_param:
                    xorg_subdir = extra_param['extra_start_dir']
                for par_name in ['preconfigopts', 'cmd_prefix', 'prefix_opt', 'installdir', 'configopts']:
                    if par_name in extra_param[par_name]:
                       exec('%s = %s' % (par_name, extra_param[par_name]))  

            os.chdir(os.path.join('..', xorg_subdir))
            cmd = "%(preconfigopts)s %(cmd_prefix)s./configure %(prefix_opt)s%(installdir)s %(configopts)s" % {
                'preconfigopts': preconfigopts,
                'cmd_prefix': cmd_prefix,
                'prefix_opt': prefix_opt,
                'installdir': c_installdir,
                'configopts': configopts,
            }

            self.log.info("    Xorg_configure: %s" % tup [0])
            print "        ... %s" % tup[0]
            run_cmd(cmd, log_all=True, simple=False)

    def build_step(self, verbose=False, path=None):
        """
        Start the actual build
        - typical: make -j X
        """

        for tup in self.cfg['Xorg_installs']:
            tuplen = len(tup)
            if tuplen < 2:
                 raise EasyBuildError("Not enough parameters for: %s", tup[0])

            xorg_subdir = '%s-%s' % (tup[0], tup[1]) 
            paracmd = ''
            prebuildopts = ''
            buildopts = ''
            if tuplen > 3:
                extra_param = tup[2]
                if 'extra_start_dir' in extra_param:
                    xorg_subdir = extra_param['extra_start_dir']
                for par_name in ['prebuildopts', 'buildopts']:
                    if par_name in extra_param[par_name]:
                       exec('%s = %s' % (par_name, extra_param[par_name]))  

            os.chdir(os.path.join('..', xorg_subdir))

            cmd = "%s make %s %s" % (prebuildopts, paracmd, buildopts)

            self.log.info("    Xorg_build: %s" % tup [0])
            print "        ... %s" % tup[0]
            run_cmd(cmd, log_all=True, simple=False, log_output=verbose)

    def install_step(self):
        """
        Create the installation in correct location
        - typical: make install
        """

        for tup in self.cfg['Xorg_installs']:
            tuplen = len(tup)
            if tuplen < 2:
                 raise EasyBuildError("Not enough parameters for: %s", tup[0])

            xorg_subdir = '%s-%s' % (tup[0], tup[1]) 
            preinstallopts = ''
            installopts = ''
            if tuplen > 3:
                extra_param = tup[2]
                if 'extra_start_dir' in extra_param:
                    xorg_subdir = extra_param['extra_start_dir']
                for par_name in ['prebuildopts', 'buildopts']:
                    if par_name in extra_param[par_name]:
                       exec('%s = %s' % (par_name, extra_param[par_name]))  

            os.chdir(os.path.join('..', xorg_subdir))

            cmd = "%s make install %s" % (preinstallopts, installopts)

            self.log.info("    Xorg_install: %s" % tup [0])
            print "        ... %s" % tup[0]
            run_cmd(cmd, log_all=True, simple=False)
