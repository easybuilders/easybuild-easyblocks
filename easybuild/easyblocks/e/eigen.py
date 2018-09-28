##
# This file is an EasyBuild reciPY as per https://github.com/easybuilders/easybuild
#
# Copyright:: Copyright 2012-2018 Uni.Lu/LCSB, NTUA
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
from distutils.version import LooseVersion

from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import copy_dir, copy_file, mkdir


class EB_Eigen(CMakeMake):
    """
    Support for building Eigen.
    """

    def configure_step(self):
        """Custom configuration procedure for Eigen."""
        # start using CMake for Eigen 3.3.4 and newer versions
        # not done for older versions, since this implies using (a dummy-built) CMake as a build dependency,
        # which is a bit strange for a header-only library like Eigen...
        if LooseVersion(self.version) >= LooseVersion('3.3.4'):
            self.cfg['separate_build_dir'] = True
            # avoid that include files are installed into include/eigen3/Eigen, should be include/Eigen
            self.cfg.update('configopts', "-DINCLUDE_INSTALL_DIR=%s" % os.path.join(self.installdir, 'include'))
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

        if LooseVersion(self.version) >= LooseVersion('3.0'):
            custom_paths['files'].append('include/signature_of_eigen3_matrix_library')

        if LooseVersion(self.version) >= LooseVersion('3.3.4'):
            custom_paths['files'].append('share/pkgconfig/eigen3.pc')

        super(EB_Eigen, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_req_guess(self):
        """
        A dictionary of possible directories to look for.
        Include CPLUS_INCLUDE_PATH as an addition to default ones
        """
        guesses = super(EB_Eigen, self).make_module_req_guess()
        guesses.update({'CPLUS_INCLUDE_PATH': ['include']})
        return guesses
