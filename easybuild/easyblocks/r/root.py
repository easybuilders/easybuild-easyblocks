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
EasyBuild support for ROOT, implemented as an easyblock

@author: Kenneth Hoste (Ghent University)
@author: Jens Timmerman (Ghent University)
"""
import os

from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools import LooseVersion
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option
from easybuild.tools.environment import setvar
from easybuild.tools.filetools import find_glob_pattern
from easybuild.tools.modules import MODULE_LOAD_ENV_HEADERS, get_software_root, get_software_version
from easybuild.tools.run import run_shell_cmd


class EB_ROOT(CMakeMake):

    @staticmethod
    def extra_options():
        """
        Define extra options needed by Geant4
        """
        extra_vars = CMakeMake.extra_options()
        extra_vars.update({
            'arch': [None, "Target architecture", CUSTOM],
        })
        extra_vars['separate_build_dir'][0] = True
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Easyblock constructor."""
        super(EB_ROOT, self).__init__(*args, **kwargs)

        # additional subdirectories specific to ROOT
        self.module_load_environment.LD_LIBRARY_PATH.append(os.path.join('lib', 'root'))
        self.module_load_environment.LIBRARY_PATH.append(os.path.join('lib', 'root'))
        self.module_load_environment.PYTHONPATH = [
            'lib',
            os.path.join('lib', 'root'),
            os.path.join('lib', 'root', 'python'),
        ]
        for cpp_header in self.module_load_environment.alias(MODULE_LOAD_ENV_HEADERS):
            cpp_header.append(os.path.join('include', 'root'))

    def configure_step(self):
        """Custom configuration for ROOT, add configure options."""

        # ROOT includes an (old) copy of LLVM;
        # if LLVM is loaded as an indirect dep, we need to make sure
        # the location to its header files is not included in $CPATH
        llvm_root = get_software_root('LLVM')
        if llvm_root:
            llvm_inc = os.path.join(llvm_root, 'include')
            cpath = os.getenv('CPATH')
            if cpath:
                new_cpath = [p for p in cpath.split(os.pathsep) if p != llvm_inc]
                self.log.info("Filtered %s from $CPATH to avoid using LLVM loaded as indirect dependency", llvm_inc)
                setvar('CPATH', os.pathsep.join(new_cpath))

        # using ./configure is deprecated/broken in recent versions, need to use CMake instead
        if LooseVersion(self.version.lstrip('v')) >= LooseVersion('6.10'):
            if self.cfg['arch']:
                raise EasyBuildError("Specified value '%s' for 'arch' is not used, should not be set", self.cfg['arch'])

            cfitsio_root = get_software_root('CFITSIO')
            if cfitsio_root:
                self.cfg.update('configopts', '-DCFITSIO=%s' % cfitsio_root)

            fftw_root = get_software_root('FFTW')
            if fftw_root:
                self.cfg.update('configopts', '-Dbuiltin_fftw3=OFF -DFFTW_DIR=%s' % fftw_root)

            gsl_root = get_software_root('GSL')
            if gsl_root:
                self.cfg.update('configopts', '-DGSL_DIR=%s' % gsl_root)

            mesa_root = get_software_root('Mesa')
            if mesa_root:
                self.cfg.update('configopts', '-DDOPENGL_INCLUDE_DIR=%s' % os.path.join(mesa_root, 'include'))
                self.cfg.update('configopts', '-DOPENGL_gl_LIBRARY=%s' % os.path.join(mesa_root, 'lib', 'libGL.so'))

            python_root = get_software_root('Python')
            if python_root:
                pyshortver = '.'.join(get_software_version('Python').split('.')[:2])
                self.cfg.update('configopts', '-DPYTHON_EXECUTABLE=%s' % os.path.join(python_root, 'bin', 'python'))
                python_inc_dir = find_glob_pattern(os.path.join(python_root, 'include', 'python%s*' % pyshortver))
                self.cfg.update('configopts', '-DPYTHON_INCLUDE_DIR=%s' % python_inc_dir)
                python_lib = find_glob_pattern(
                    os.path.join(python_root, 'lib', 'libpython%s*.so' % pyshortver))
                self.cfg.update('configopts', '-DPYTHON_LIBRARY=%s' % python_lib)

            if get_software_root('X11'):
                self.cfg.update('configopts', '-Dx11=ON')

            sysroot = build_option('sysroot')
            if sysroot:
                self.cfg.update('configopts', '-DDEFAULT_SYSROOT=%s' % sysroot)

            CMakeMake.configure_step(self)
        else:
            if self.cfg['arch'] is None:
                raise EasyBuildError("No architecture specified to pass to configure script")

            self.cfg.update('configopts', "--etcdir=%s/etc/root " % self.installdir)

            cmd = "%s ./configure %s --prefix=%s %s" % (self.cfg['preconfigopts'],
                                                        self.cfg['arch'],
                                                        self.installdir,
                                                        self.cfg['configopts'])

            run_shell_cmd(cmd)

    def sanity_check_step(self):
        """Custom sanity check for ROOT."""
        custom_paths = {
            'files': ['bin/root.exe'],
            'dirs': ['include', 'lib'],
        }
        if LooseVersion(self.version.lstrip('v')) >= LooseVersion('6'):
            custom_paths['files'].append('bin/root')

        custom_commands = []
        if get_software_root('Python'):
            custom_commands.append("python -c 'import ROOT'")

        super(EB_ROOT, self).sanity_check_step(custom_commands=custom_commands, custom_paths=custom_paths)

    def make_module_extra(self):
        """Custom extra module file entries for ROOT."""
        txt = super(EB_ROOT, self).make_module_extra()
        txt += self.module_generator.set_environment('ROOTSYS', self.installdir)
        return txt
