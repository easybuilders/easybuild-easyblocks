##
# This file is an EasyBuild reciPY as per https://github.com/easybuilders/easybuild
#
# Copyright:: Copyright 2012-2025 Uni.Lu/LCSB, NTUA
# Authors::   Cedric Laczny <cedric.laczny@uni.lu>, Fotis Georgatos <fotis@cern.ch>, Kenneth Hoste
# License::   MIT/GPL
# $Id$
#
# This work implements a part of the HPCBIOS project and is a component of the policy:
# http://hpcbios.readthedocs.org/en/latest/HPCBIOS_2012-94.html
##
"""
EasyBuild support for building and installing Eigen, implemented as an easyblock

@author: Cedric Laczny (Uni.Lu)
@author: Fotis Georgatos (Uni.Lu)
@author: Kenneth Hoste (Ghent University)
"""

import os
import shutil
from easybuild.tools import LooseVersion

from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.tools.filetools import copy_dir, copy_file, mkdir, apply_regex_substitutions


class EB_Eigen(CMakeMake):
    """
    Support for building Eigen.
    """

    def configure_step(self):
        """Custom configuration procedure for Eigen."""
        # start using CMake for Eigen 3.3.4 and newer versions
        # not done for older versions, since this implies using CMake as a build dependency
        if LooseVersion(self.version) >= LooseVersion('3.3.4'):
            # Install headers as include/Eigen/*.h instead of the default include/eigen3/Eigen/*.h to make it easier
            # for dependencies to find the headers without setting anything in addition
            # Note: Path must be relative to the install prefix!
            self.cfg.update('configopts', "-DINCLUDE_INSTALL_DIR=%s" % 'include')
            # Patch to make the relative path actually work.
            regex_subs = [('CACHE PATH ("The directory relative to CMAKE.*PREFIX)', r'CACHE STRING \1')]
            apply_regex_substitutions(os.path.join(self.cfg['start_dir'], 'CMakeLists.txt'), regex_subs)
            CMakeMake.configure_step(self)

    def build_step(self):
        """Custom build procedure for Eigen."""
        if LooseVersion(self.version) >= LooseVersion('3.3.4'):
            CMakeMake.build_step(self)

    def install_step(self):
        """
        Install by copying files to install dir
        """
        if LooseVersion(self.version) >= LooseVersion('3.3.4'):
            CMakeMake.install_step(self)
        else:
            mkdir(os.path.join(self.installdir, 'include'), parents=True)
            for subdir in ['Eigen', 'unsupported']:
                srcdir = os.path.join(self.cfg['start_dir'], subdir)
                destdir = os.path.join(self.installdir, os.path.join('include', subdir))
                copy_dir(srcdir, destdir, ignore=shutil.ignore_patterns('CMakeLists.txt'))

            if LooseVersion(self.version) >= LooseVersion('3.0'):
                srcfile = os.path.join(self.cfg['start_dir'], 'signature_of_eigen3_matrix_library')
                destfile = os.path.join(self.installdir, 'include/signature_of_eigen3_matrix_library')
                copy_file(srcfile, destfile)

    def sanity_check_step(self):
        """Custom sanity check for Eigen."""

        # both in Eigen 2.x an 3.x
        include_files = ['Cholesky', 'Core', 'Dense', 'Eigen', 'Geometry', 'LU',
                         'QR', 'QtAlignedMalloc', 'SVD', 'Sparse', 'StdVector']

        if LooseVersion(self.version) >= LooseVersion('3.0'):
            # only in 3.x
            include_files.extend(['CholmodSupport', 'Eigenvalues', 'Householder',
                                  'IterativeLinearSolvers', 'Jacobi', 'OrderingMethods', 'PaStiXSupport',
                                  'PardisoSupport', 'SparseCholesky', 'SparseCore', 'StdDeque', 'StdList',
                                  'SuperLUSupport', 'UmfPackSupport'])
        custom_paths = {
            'files': ['include/Eigen/%s' % x for x in include_files],
            'dirs': []
        }
        custom_commands = []

        if LooseVersion(self.version) >= LooseVersion('3.0'):
            custom_paths['files'].append('include/signature_of_eigen3_matrix_library')

        if LooseVersion(self.version) >= LooseVersion('3.3.4'):
            custom_paths['files'].append(os.path.join('share', 'pkgconfig', 'eigen3.pc'))
            cmake_config_dir = os.path.join('share', 'eigen3', 'cmake')
            custom_paths['files'].append(os.path.join(cmake_config_dir, 'Eigen3Config.cmake'))
            # Check that CMake config files don't contain duplicated prefix
            custom_commands.append("! grep -q -r '${PACKAGE_PREFIX_DIR}/${PACKAGE_PREFIX_DIR}' %s"
                                   % os.path.join(self.installdir, cmake_config_dir))

        super(EB_Eigen, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
