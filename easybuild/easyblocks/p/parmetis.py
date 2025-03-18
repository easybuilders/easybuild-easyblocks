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
EasyBuild support for ParMETIS, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
@author: Alex Domingo (Vrije Universiteit Brussel)
"""
import os
import shutil
from easybuild.tools import LooseVersion

from easybuild.framework.easyblock import EasyBlock
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import mkdir, symlink, remove_file
from easybuild.tools.run import run_shell_cmd
from easybuild.tools.systemtools import get_shared_lib_ext


class EB_ParMETIS(EasyBlock):
    """Support for building and installing ParMETIS."""

    def __init__(self, *args, **kwargs):
        """Easyblock constructor."""

        super(EB_ParMETIS, self).__init__(*args, **kwargs)

        self.config_shared = False
        self.config_static = False

    def configure_step(self):
        """Configure ParMETIS build.
        For versions of ParMETIS < 4 , METIS is a seperate build
        New versions of ParMETIS include METIS

        Run 'cmake' in the build dir to get rid of a 'user friendly'
        help message that is displayed without this step.
        """

        # Detect if this iteration is building static or shared libs to do proper sanity check
        static_build = True
        config_true = ['1', 'ON', 'YES', 'TRUE', 'Y']  # True values in CMake
        for configopt in self.cfg['configopts'].split():
            if 'SHARED' in configopt and any(trueval in configopt for trueval in config_true):
                static_build = False

        if static_build:
            self.config_static = True
        else:
            self.config_shared = True

        if LooseVersion(self.version) >= LooseVersion("4"):
            # tested with 4.0.2, now actually requires cmake to be run first
            # for both parmetis and metis

            self.cfg.update('configopts', '-DMETIS_PATH=../metis -DGKLIB_PATH=../metis/GKlib')

            self.cfg.update('configopts', '-DOPENMP="%s"' % self.toolchain.get_flag('openmp'))

            if self.toolchain.options.get('usempi', None):
                self.cfg.update('configopts', '-DCMAKE_C_COMPILER="$MPICC"')

            if self.toolchain.options['pic']:
                self.cfg.update('configopts', '-DCMAKE_C_FLAGS="-fPIC"')

            self.parmetis_builddir = 'build'
            try:
                os.chdir(self.parmetis_builddir)
                cmd = 'cmake .. %s -DCMAKE_INSTALL_PREFIX="%s"' % (self.cfg['configopts'],
                                                                   self.installdir)
                run_shell_cmd(cmd)
                os.chdir(self.cfg['start_dir'])
            except OSError as err:
                raise EasyBuildError("Running cmake in %s failed: %s", self.parmetis_builddir, err)

    def build_step(self):
        """Build ParMETIS (and METIS) using build_step."""

        paracmd = f'-j {self.cfg.parallel}' if self.cfg.parallel > 1 else ''

        self.cfg.update('buildopts', 'LIBDIR=""')

        if self.toolchain.options['usempi']:
            if self.toolchain.options['pic']:
                self.cfg.update('buildopts', 'CC="$MPICC -fPIC"')
            else:
                self.cfg.update('buildopts', 'CC="$MPICC"')

        cmd = "%s make %s %s" % (self.cfg['prebuildopts'], paracmd, self.cfg['buildopts'])

        # run make in build dir as well for recent version
        if LooseVersion(self.version) >= LooseVersion("4"):
            try:
                os.chdir(self.parmetis_builddir)
                run_shell_cmd(cmd)
                os.chdir(self.cfg['start_dir'])
            except OSError as err:
                raise EasyBuildError("Running cmd '%s' in %s failed: %s", cmd, self.parmetis_builddir, err)
        else:
            run_shell_cmd(cmd)

    def install_step(self):
        """
        Install by copying files over to the right places.

        Also create symlinks where expected by other software (Lib directory).
        """
        includedir = os.path.join(self.installdir, 'include')
        libdir = os.path.join(self.installdir, 'lib')

        if LooseVersion(self.version) >= LooseVersion("4"):
            # includedir etc changed in v4, use a normal make install
            cmd = "make install %s" % self.cfg['installopts']
            try:
                os.chdir(self.parmetis_builddir)
                run_shell_cmd(cmd)
                os.chdir(self.cfg['start_dir'])
            except OSError as err:
                raise EasyBuildError("Running '%s' in %s failed: %s", cmd, self.parmetis_builddir, err)

            # libraries
            try:
                src = os.path.join(self.cfg['start_dir'], 'build', 'libmetis', 'libmetis.a')
                dst = os.path.join(libdir, 'libmetis.a')
                shutil.copy2(src, dst)
            except OSError as err:
                raise EasyBuildError("Copying files to installation dir failed: %s", err)

            # include files
            try:
                src = os.path.join(self.cfg['start_dir'], 'build', 'metis', 'include', 'metis.h')
                dst = os.path.join(includedir, 'metis.h')
                shutil.copy2(src, dst)
            except OSError as err:
                raise EasyBuildError("Copying files to installation dir failed: %s", err)

        else:
            mkdir(libdir)
            mkdir(includedir)

            # libraries
            try:
                for fil in ['libmetis.a', 'libparmetis.a']:
                    src = os.path.join(self.cfg['start_dir'], fil)
                    dst = os.path.join(libdir, fil)
                    shutil.copy2(src, dst)
            except OSError as err:
                raise EasyBuildError("Copying files to installation dir failed: %s", err)

            # include files
            try:
                src = os.path.join(self.cfg['start_dir'], 'parmetis.h')
                dst = os.path.join(includedir, 'parmetis.h')
                shutil.copy2(src, dst)
                # some applications (SuiteSparse) can only use METIS (not ParMETIS), but header files are the same
                dst = os.path.join(includedir, 'metis.h')
                shutil.copy2(src, dst)
            except OSError as err:
                raise EasyBuildError("Copying files to installation dir failed: %s", err)

        # other applications depending on ParMETIS (SuiteSparse for one) look for both ParMETIS libraries
        # and header files in the Lib directory (capital L). The following symlink are hence created.
        try:
            caplibdir = os.path.join(self.installdir, 'Lib')
            remove_file(caplibdir)
            symlink(libdir, caplibdir)
            for header_file in ['metis.h', 'parmetis.h']:
                header_path = os.path.join(libdir, header_file)
                remove_file(header_path)
                symlink(os.path.join(includedir, header_file), header_path)
        except OSError as err:
            raise EasyBuildError("Something went wrong during symlink creation: %s", err)

    def sanity_check_step(self):
        """Custom sanity check for ParMETIS."""

        parmetis_libs = [os.path.join('lib', 'libmetis.a')]
        # Add static and shared libs depending on configopts
        if self.config_shared:
            shlib_ext = get_shared_lib_ext()
            parmetis_libs.append(os.path.join('lib', 'libparmetis.%s' % shlib_ext))
        if self.config_static:
            parmetis_libs.append(os.path.join('lib', 'libparmetis.a'))

        custom_paths = {
            'files': ['include/%smetis.h' % x for x in ["", "par"]] + parmetis_libs,
            'dirs': ['Lib']
        }

        super(EB_ParMETIS, self).sanity_check_step(custom_paths=custom_paths)
