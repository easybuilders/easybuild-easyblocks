##
# Copyright 2018-2024 Ghent University
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
EasyBuild support for building and installing CFDEMcoupling, implemented as an easyblock

@author: Kenneth Hoste (Ghent University)
"""
import glob
import os

import easybuild.tools.environment as env
import easybuild.tools.toolchain as toolchain
from easybuild.framework.easyblock import EasyBlock
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import copy_file, mkdir, move_file
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.run import run_cmd


class EB_CFDEMcoupling(EasyBlock):
    """Support for building/installing CFDEMcoupling."""

    def __init__(self, *args, **kwargs):
        """Initialisation of custom class variables for CFDEMcoupling."""
        super(EB_CFDEMcoupling, self).__init__(*args, **kwargs)

        self.build_in_installdir = True

        self.cfdem_project_dir = os.path.join(self.installdir, '%s-%s' % (self.name, self.version))
        self.liggghts_dir = os.path.join(self.installdir, 'LIGGGHTS-%s' % self.version)

    def configure_step(self):
        """Set up environment for building/installing CFDEMcoupling."""

        # rename top-level directory to CFDEMcoupling-<version>
        top_dirs = os.listdir(self.builddir)

        for (pkgname, target_dir) in [('CFDEMcoupling', self.cfdem_project_dir), ('LIGGGHTS', self.liggghts_dir)]:
            pkg_topdirs = [d for d in top_dirs if d.startswith(pkgname)]
            if len(pkg_topdirs) == 1:
                orig_dir = os.path.join(self.builddir, pkg_topdirs[0])
                move_file(orig_dir, target_dir)
            else:
                error_msg = "Failed to find subdirectory for %s in %s %s (missing sources for %s?)",
                raise EasyBuildError(error_msg, pkgname, self.builddir, top_dirs, pkgname)

        env.setvar('CFDEM_VERSION', self.version)
        env.setvar('CFDEM_PROJECT_DIR', self.cfdem_project_dir)

        # define $CFDEM_PROJECT_USER_DIR to an empty existing directory
        project_user_dir = os.path.join(self.builddir, 'project_user_dir')
        env.setvar('CFDEM_PROJECT_USER_DIR', project_user_dir)
        mkdir(project_user_dir, parents=True)

        cfdem_bashrc = os.path.join(self.cfdem_project_dir, 'src', 'lagrangian', 'cfdemParticle', 'etc', 'bashrc')
        env.setvar('CFDEM_bashrc', cfdem_bashrc)

        env.setvar('CFDEM_LIGGGHTS_SRC_DIR', os.path.join(self.liggghts_dir, 'src'))
        env.setvar('CFDEM_LIGGGHTS_MAKEFILE_NAME', 'auto')

        lpp_dirs = glob.glob(os.path.join(self.builddir, 'LPP-*'))
        if len(lpp_dirs) == 1:
            env.setvar('CFDEM_LPP_DIR', lpp_dirs[0])
        else:
            raise EasyBuildError("Failed to isolate LPP-* directory in %s", self.builddir)

        # build in parallel
        env.setvar("WM_NCOMPPROCS", str(self.cfg['parallel']))

        vtk_root = get_software_root('VTK')
        if vtk_root:
            vtk_ver_maj_min = '.'.join(get_software_version('VTK').split('.')[:2])
            vtk_inc = os.path.join(vtk_root, 'include', 'vtk-%s' % vtk_ver_maj_min)
            if os.path.exists(vtk_inc):
                env.setvar('VTK_INC_USR', '-I%s' % vtk_inc)
            else:
                raise EasyBuildError("Expected directory %s does not exist!", vtk_inc)

            vtk_lib = os.path.join(vtk_root, 'lib')
            if os.path.exists(vtk_lib):
                env.setvar('VTK_LIB_USR', '-L%s' % vtk_lib)
            else:
                raise EasyBuildError("Expected directory %s does not exist!", vtk_lib)
        else:
            raise EasyBuildError("VTK not included as dependency")

        # can't seem to use defined 'cfdemSysTest' alias, so call cfdemSystemTest.sh script directly...
        cmd = "source $CFDEM_bashrc && $CFDEM_SRC_DIR/lagrangian/cfdemParticle/etc/cfdemSystemTest.sh"
        run_cmd(cmd, log_all=True, simple=True, log_ok=True)

    def build_step(self):
        """Custom build procedure for CFDEMcoupling."""

        if get_software_root('OpenFOAM'):
            openfoam_ver = get_software_version('OpenFOAM')
            openfoam_maj_ver = openfoam_ver.split('.')[0]
        else:
            raise EasyBuildError("OpenFOAM not included as dependency")

        # make sure expected additionalLibs_* file is available
        addlibs_subdir = os.path.join('src', 'lagrangian', 'cfdemParticle', 'etc', 'addLibs_universal')
        src_addlibs = os.path.join(self.cfdem_project_dir, addlibs_subdir, 'additionalLibs_%s.x' % openfoam_maj_ver)
        target_addlibs = os.path.join(self.cfdem_project_dir, addlibs_subdir, 'additionalLibs_%s' % openfoam_ver)
        copy_file(src_addlibs, target_addlibs)

        # can't seem to use defined 'cfdemCompCFDEMall' alias...
        cmd = "$CFDEM_SRC_DIR/lagrangian/cfdemParticle/etc/compileCFDEMcoupling_all.sh"
        run_cmd("source $FOAM_BASH && source $CFDEM_bashrc && %s" % cmd, log_all=True, simple=True, log_ok=True)

    def install_step(self):
        """No custom install procedure for CFDEMcoupling."""
        pass

    def sanity_check_step(self):
        """Custom sanity check for CFDEMcoupling."""
        comp_fam = self.toolchain.comp_family()
        if comp_fam == toolchain.GCC:
            wm_compiler = 'Gcc'
        elif comp_fam == toolchain.INTELCOMP:
            wm_compiler = 'Icc'
        else:
            raise EasyBuildError("Unknown compiler family, don't know how to set WM_COMPILER")

        psubdir = "linux64%sDPInt32Opt" % wm_compiler

        cfdem_base_dir = os.path.basename(self.cfdem_project_dir)
        bins = ['cfdemPostproc', 'cfdemSolverIB', 'cfdemSolverPiso', 'cfdemSolverPisoScalar', 'cfdemSolverPisoSTM']
        custom_paths = {
            'files': [os.path.join(cfdem_base_dir, 'platforms', psubdir, 'bin', b) for b in bins],
            'dirs': [os.path.join(cfdem_base_dir, 'platforms', psubdir, 'lib')],
        }
        super(EB_CFDEMcoupling, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_extra(self):
        """Custom extra module file entries for CFDEMcoupling."""

        txt = super(EB_CFDEMcoupling, self).make_module_extra()

        txt += self.module_generator.set_environment('CFDEM_VERSION', self.version)
        txt += self.module_generator.set_environment('CFDEM_PROJECT_DIR', self.cfdem_project_dir)
        txt += self.module_generator.set_environment('CFDEM_LIGGGHTS_SRC_DIR', os.path.join(self.liggghts_dir, 'src'))
        txt += self.module_generator.set_environment('CFDEM_LIGGGHTS_MAKEFILE_NAME', 'auto')

        cfdem_bashrc = os.path.join(self.cfdem_project_dir, 'src', 'lagrangian', 'cfdemParticle', 'etc', 'bashrc')
        txt += self.module_generator.set_environment('CFDEM_bashrc', cfdem_bashrc)

        return txt
