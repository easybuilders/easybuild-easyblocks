##
# Copyright 2019-2019 Ghent University
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
EasyBuild support for building and installing CUTEst, implemented as an easyblock

@author: Kenneth Hoste (Ghent University)
"""
from distutils.version import LooseVersion
import glob
import os

import easybuild.tools.environment as env
import easybuild.tools.toolchain as toolchain
from easybuild.framework.easyblock import EasyBlock
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import apply_regex_substitutions, change_dir, remove_file
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.run import run_cmd_qa


COMPONENTS = ['ARCHDefs', 'CUTEst', 'SIFDecode']


class EB_CUTEst(EasyBlock):
    """Support for building/installing CUTEst."""

    def __init__(self, *args, **kwargs):
        """Constructor for CUTEst easyblock."""
        super(EB_CUTEst, self).__init__(*args, **kwargs)

        self.build_in_installdir = True

        self.subdirs = {}

        self.matlab_root = None

    def prepare_step(self):
        """Custom prepare step for CUTEst."""
        super(EB_CUTEst, self).prepare_step()

        # determine subdirectories for each component
        for comp in COMPONENTS:
            paths = glob.glob(os.path.join(self.installdir, comp + '-*'))
            if len(paths) == 1:
                self.subdirs[comp] = os.path.basename(paths[0])
            else:
                raise EasyBuildError("Failed to isolate %s subdirectory: %s", comp, paths)

        self.matlab_root = get_software_root('MATLAB')

    def configure_step(self):
        """Custom configuration procedure for CUTEst."""

        # set required environment variables for subdirectories
        for comp in COMPONENTS:
            env.setvar(comp.upper(), os.path.join(self.installdir, self.subdirs[comp]))

        if self.matlab_root:
            env.setvar('MYMATLAB', self.matlab_root)

    def build_step(self):
        """No separate build procedure for CUTEst."""
        pass

    def test_step(self):
        """No separate test procedure for CUTEst."""
        pass

    def install_step(self):
        """Custom install procedure for CUTEst."""

        archdefs_subdir = self.subdirs['ARCHDefs']
        cutest_subdir = self.subdirs['CUTEst']

        # patch files/scripts to get rid hardcoded versions in compiler commands
        regexs = [
            (r'gcc-[0-9.]+', r'gcc'),
            (r'gfortran-[0-9.]+', r'gfortran'),
        ]
        files_to_patch = [
            # corresponds to "GNU gfortran 6 compiler" option
            os.path.join(self.installdir, archdefs_subdir, 'compiler.pc.lnx.gf6'),
            os.path.join(self.installdir, archdefs_subdir, 'compiler.pc64.lnx.gf6'),
            os.path.join(self.installdir, archdefs_subdir, 'bin', 'select_arch'),
        ]
        for fp in files_to_patch:
            apply_regex_substitutions(fp, regexs)

            # need to remove backup of original, since it causes problems...
            remove_file(fp + '.orig.eb')

        # patch install/helper scripts so run_cmd_qa can see the questions and 'read' wait until newline is entered
        regexs = [
            (r'read .* (["\'].*["\']) .* ([a-zA-Z]+)', r'echo \1; read -r \2'),
        ]

        helper_functions_path = os.path.join(self.installdir, archdefs_subdir, 'bin', 'helper_functions')
        apply_regex_substitutions(helper_functions_path, regexs)

        helper_functions_path = os.path.join(self.installdir, cutest_subdir, 'bin', 'install_cutest_main')
        apply_regex_substitutions(helper_functions_path, regexs)

        change_dir(os.path.join(self.installdir, cutest_subdir))

        # regex pattern to capture id of selected option
        id_prefix_pattern = r"\s*\((?P<id>[0-9]+)\) "

        # figure out whether or not to build CUTEst MATAB interface (and for which version)
        if self.matlab_root:
            matlab_answer = 'Y'

            matlab_version = get_software_version('MATLAB')
            if LooseVersion(matlab_version) >= LooseVersion('2018a'):
                matlab_option = id_prefix_pattern + "R2018a or later"
            elif LooseVersion(matlab_version) >= LooseVersion('2016b'):
                matlab_option = id_prefix_pattern + "R2016b-R2017b"
            else:
                raise EasyBuildError("MATLAB version too old, don't know which option to pick")

        else:
            matlab_answer = 'N'
            matlab_option = ''

        # determine correct option to pick for C and Fortran compilers, based on toolchain compiler family
        comp_fam = self.toolchain.comp_family()

        if comp_fam == toolchain.INTELCOMP:  # @UndefinedVariable

            fortran_comp = id_prefix_pattern + r"Intel ifort compiler"
            gcc_comp = id_prefix_pattern + r"ICC for 64-bit"

        elif comp_fam == toolchain.GCC:  # @UndefinedVariable

            gcc_ver = get_software_version('GCC')

            if LooseVersion(gcc_ver) >= LooseVersion('6.0'):
                fortran_comp = id_prefix_pattern + r"GNU gfortran 6 compiler"
            else:
                fortran_comp = id_prefix_pattern + r"GNU gfortran compiler"

            gcc_comp = id_prefix_pattern + r"GCC"

        else:
            raise EasyBuildError("Unknown compiler family: %s", comp_fam)

        qa = {
            "Do you wish to install GALAHAD (Y/n)?": 'n',
            "Do you wish to install CUTEst (Y/n)?": 'Y',
            "Do you require the CUTEst-Matlab interface (y/N)?": matlab_answer,
            "Would you like to compile SIFDecode ... (Y/n)?": 'Y',
            "Would you like to compile CUTEst ... (Y/n)?": 'Y',
            "CUTEst may be compiled in (S)ingle or (D)ouble precision or (B)oth.\n"
            "Which precision do you require for the installed subset (D/s/b) ?": 'D',
        }

        options = r"(\s*\([0-9]+\).*\n)*"
        std_qa = {
            r"Would you like to review and modify .*": 'N',
            r"Select platform\n" + options + r"\s*\((?P<id>6)\) PC with generic 64-bit processor\n" + options: '%(id)s',
            r"Select operating system(\n|.)+\(3\) Linux": '3',
            r"Select fortran compiler\n" + options + fortran_comp + '\n' + options: '%(id)s',
            r"Select C compiler\n" + options + gcc_comp + options: '%(id)s',
            r"Select Matlab version\n\n" + options + matlab_option + options: '%(id)s',
        }

        cmd = os.path.join(self.installdir, archdefs_subdir, 'bin', 'install_optrove')
        run_cmd_qa(cmd, qa, std_qa=std_qa, log_all=True, simple=True, log_ok=True)

    def sanity_check_step(self):
        """Custom sanity check for CUTEst."""

        custom_paths = {
            'files': [os.path.join(self.subdirs['CUTEst'], 'bin', 'runcutest'),
                      os.path.join(self.subdirs['SIFDecode'], 'bin', 'sifdecoder')],
            'dirs': [os.path.join(self.subdirs['SIFDecode'], 'man'), os.path.join(self.subdirs['CUTEst'], 'man')],
        }
        super(EB_CUTEst, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_req_guess(self):
        """Custom guesses for environment variables (PATH, ...) for CUTEst."""

        guesses = super(EB_CUTEst, self).make_module_req_guess()

        guesses.update({
            'PATH': [os.path.join(self.subdirs['CUTEst'], 'bin'), os.path.join(self.subdirs['SIFDecode'], 'bin')],
            'MANPATH': [os.path.join(self.subdirs['CUTEst'], 'man'), os.path.join(self.subdirs['SIFDecode'], 'man')],
        })

        return guesses

    def make_module_extra(self):
        """Custom extra module file entries for CUTEst."""

        txt = super(EB_CUTEst, self).make_module_extra()

        for comp in COMPONENTS:
            comp_path = os.path.join(self.installdir, self.subdirs[comp])
            txt += self.module_generator.set_environment(comp.upper(), comp_path)

        if self.matlab_root:
            txt += self.module_generator.set_environment('MYMATLAB', self.matlab_root)
            matlab_subdir = os.path.join(self.subdirs['CUTEst'], 'src', 'matlab')
            txt += self.module_generator.prepend_paths('MATLABPATH', [matlab_subdir])

        return txt
