##
# Copyright 2009-2025 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://www.vscentrum.be),
# Flemish Research Foundation (FWO) (http://www.fwo.be/en)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# https://github.com/easybuilders/easybuild
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
Geant4 support, implemented as an easyblock.

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
"""

import os

from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools import LooseVersion


class EB_Geant4(CMakeMake):
    """
    Support for building Geant4.
    """

    @staticmethod
    def extra_options():
        """
        Define extra options needed by Geant4
        """
        extra_vars = CMakeMake.extra_options()
        extra_vars.update({
            'G4ABLAVersion': [None, "G4ABLA version", CUSTOM],
            'G4NDLVersion': [None, "G4NDL version", CUSTOM],
            'G4EMLOWVersion': [None, "G4EMLOW version", CUSTOM],
            'PhotonEvaporationVersion': [None, "PhotonEvaporation version", CUSTOM],
            'G4RadioactiveDecayVersion': [None, "G4RadioactiveDecay version", CUSTOM],
        })
        # Requires out-of-source build
        extra_vars['separate_build_dir'][0] = True
        return extra_vars

    def make_module_extra(self):
        """Define Geant4-specific environment variables in module file."""
        g4version = '.'.join(self.version.split('.')[:2])

        # '10.01.p03' -> '10.1.3'
        shortver = self.version.replace('.0', '.').replace('.p0', '.')
        datadst = os.path.join(self.installdir, 'share', '%s-%s' % (self.name, shortver), 'data')

        txt = super(EB_Geant4, self).make_module_extra()
        txt += self.module_generator.set_environment('G4INSTALL', self.installdir)
        # no longer needed in > 9.5, but leave it there for now.
        txt += self.module_generator.set_environment('G4VERSION', g4version)

        incdir = os.path.join(self.installdir, 'include')
        txt += self.module_generator.set_environment('G4INCLUDE', os.path.join(incdir, 'Geant4'))
        txt += self.module_generator.set_environment('G4LIB', os.path.join(self.installdir, 'lib64', 'Geant4'))

        if self.cfg['PhotonEvaporationVersion']:
            g4levelgammadata = os.path.join(datadst, 'PhotonEvaporation%s' % self.cfg['PhotonEvaporationVersion'])
            txt += self.module_generator.set_environment('G4LEVELGAMMADATA', g4levelgammadata)

        if self.cfg['G4RadioactiveDecayVersion']:
            g4radioactivedata = os.path.join(datadst, 'RadioactiveDecay%s' % self.cfg['G4RadioactiveDecayVersion'])
            txt += self.module_generator.set_environment('G4RADIOACTIVEDATA', g4radioactivedata)

        if self.cfg['G4EMLOWVersion']:
            g4ledata = os.path.join(datadst, 'G4EMLOW%s' % self.cfg['G4EMLOWVersion'])
            txt += self.module_generator.set_environment('G4LEDATA', g4ledata)

        if self.cfg['G4NDLVersion']:
            g4neutronhpdata = os.path.join(datadst, 'G4NDL%s' % self.cfg['G4NDLVersion'])
            txt += self.module_generator.set_environment('G4NEUTRONHPDATA', g4neutronhpdata)

        return txt

    def sanity_check_step(self):
        """
        Custom sanity check for Geant4
        """
        bin_files = ["bin/geant4-config", "bin/geant4.sh", "bin/geant4.csh"]
        libs = ['analysis', 'event', 'GMocren', 'materials', 'readout', 'Tree', 'VRML']

        # G4Persistency library was split up in Geant v11.2,
        # see https://geant4.web.cern.ch/download/release-notes/notes-v11.2.0.html
        if LooseVersion(self.version) >= LooseVersion('11.2'):
            libs.extend(['gdml', 'geomtext', 'mctruth', 'geomtext'])
        else:
            libs.append('persistency')

        lib_files = ["lib64/libG4%s.so" % x for x in libs]
        include_dir = 'include/Geant4'

        custom_paths = {
            'files': bin_files + lib_files,
            'dirs': [include_dir],
        }

        super(EB_Geant4, self).sanity_check_step(custom_paths)
