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
EasyBuild support for ABAQUS, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
@author: Simon Branford (University of Birmingham)
"""
import glob
import os

from easybuild.easyblocks.generic.binary import Binary
from easybuild.framework.easyblock import EasyBlock
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools import LooseVersion
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.environment import setvar
from easybuild.tools.filetools import change_dir, symlink, write_file
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_shell_cmd
from easybuild.tools.systemtools import get_os_name


class EB_ABAQUS(Binary):
    """Support for installing ABAQUS."""

    @staticmethod
    def extra_options():
        extra_vars = {
            'with_fe_safe': [None, "Enable installation of fe-safe (if None: auto-enable for ABAQUS >= 2020)", CUSTOM],
            'with_tosca': [None, "Enable installation of Tosca (if None: auto-enable for ABAQUS >= 2020)", CUSTOM],
        }
        return Binary.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        """Initialisation of custom class variables for ABAQUS."""
        super(EB_ABAQUS, self).__init__(*args, **kwargs)
        self.replayfile = None

        if self.cfg['with_tosca'] is None and LooseVersion(self.version) >= LooseVersion('2020'):
            self.log.info("Auto-enabling installation of Tosca components for ABAQUS versions >= 2020")
            self.cfg['with_tosca'] = True

        if self.cfg['with_fe_safe'] is None and LooseVersion(self.version) >= LooseVersion('2020'):
            self.log.info("Auto-enabling installation of fe-safe components for ABAQUS versions >= 2020")
            self.cfg['with_fe_safe'] = True

        # add custom paths to $PATH
        path_subdirs = ['Commands']
        if self.cfg['with_tosca']:
            path_subdirs.append(os.path.join('cae', 'linux_a64', 'code', 'command'))
        self.module_load_environment.PATH.extend(path_subdirs)

    def extract_step(self):
        """Use default extraction procedure instead of the one for the Binary easyblock."""
        EasyBlock.extract_step(self)

    def configure_step(self):
        """Configure ABAQUS installation."""
        if LooseVersion(self.version) >= LooseVersion('2016'):
            # Rocky Linux isn't recognized; faking it as RHEL
            if get_os_name() in ['Rocky Linux', 'AlmaLinux']:
                setvar('DISTRIB_ID', 'RedHatEnterpriseServer')
            # skip checking of Linux version
            setvar('DSY_Force_OS', 'linux_a64')
            # skip checking of license server
            setvar('NOLICENSECHECK', 'true')
        else:
            self.replayfile = os.path.join(self.builddir, "installer.properties")
            txt = '\n'.join([
                "INSTALLER_UI=SILENT",
                "USER_INSTALL_DIR=%s" % self.installdir,
                "MAKE_DEF_VER=true",
                "DOC_ROOT=UNDEFINED",
                "DOC_ROOT_TYPE=false",
                "DOC_ROOT_ESCAPED=UNDEFINED",
                "ABAQUSLM_LICENSE_FILE=@abaqusfea",
                "LICENSE_SERVER_TYPE=FLEXNET",
                "PRODUCT_NAME=Abaqus %s" % self.version,
                "TMPDIR=%s" % self.builddir,
                "INSTALL_MPI=1",
            ])
            write_file(self.replayfile, txt)

    def install_step(self):
        """Install ABAQUS using 'setup'."""
        if LooseVersion(self.version) >= LooseVersion('2016'):
            change_dir(os.path.join(self.cfg['start_dir'], '1'))
            qa = [
                (r"Enter selection \(default: Install\):", ''),
                (r"Enter selection \(default: Close\):", ''),
            ]
            no_qa = [
                r"___",
                r"\(\d+\s*[KM]B\)",
                r"\.\.\.$",
            ]

            # Match string for continuing on with the selected items
            nextstr = r"Enter selection \(default: Next\):\s*"

            # Allow for selection or deselection of components from lines of the form:
            #   5 [*] Tosca Fluid
            # This uses nextstr to make sure we only match the latest output in the Q&A process;
            # negative lookahead (?!___) is used to exclude ___...___ lines, to avoid matching across questions;
            # *? to use non-greedy matching in combination with negative lookahead
            # (to avoid excessive backtracking by regex engine)
            selectionstr = r"\s*(?P<nr>[-0-9]+) %%s %%s.*\n((?!%s)(?!___).*\n)*?%s" % (nextstr, nextstr)

            installed_docs = False  # hard disabled, previous support was actually incomplete

            qa.extend([
                # disable Extended Product Documentation because it has a troublesome Java dependency
                (selectionstr % (r"\[*\]", "Extended Product Documentation"), '%(nr)s'),
                # enable all ABAQUS components
                (selectionstr % (r"\[ \]", "Abaqus"), '%(nr)s'),
                (selectionstr % (r"\[ \]", "Cosimulation Services"), '%(nr)s'),
                # enable 3DSFlow Solver (used to be called "Abaqus/CFD Solver")
                (selectionstr % (r"\[ \]", "3DSFlow Solver"), '%(nr)s'),
            ])

            # disable/enable fe-safe components
            if self.cfg['with_fe_safe']:
                qa.append((selectionstr % (r"\[ \]", ".*fe-safe"), '%(nr)s'))
            else:
                qa.append((selectionstr % (r"\[\*\]", ".*fe-safe"), '%(nr)s'))

            # Disable/enable Tosca
            if self.cfg['with_tosca']:
                qa.append((selectionstr % (r"\[ \]", "Tosca.*"), '%(nr)s'))
            else:
                qa.append((selectionstr % (r"\[\*\]", "Tosca.*"), '%(nr)s'))

            qa.extend([
                # disable CloudView
                (r"(?P<cloudview>[0-9]+) \[X\] Search using CloudView\nEnter selection:", '%(cloudview)s\n\n'),
                # accept default port for documentation server
                (r"Check that the port is free.\nDefault \[[0-9]+\]:", '\n'),
                # disable feedback by users
                (r"(?P<feedback>[0-9]+) \[X\] Allow users to send feedback.\nEnter selection:", '%(feedback)s\n\n'),
                # disable reverse proxy
                (r"(?P<proxy>[0-9]+) \[X\] Use a reverse proxy.\nEnter selection:", '%(proxy)s\n\n'),
                # Disable Isight
                (selectionstr % (r"\[\*\]", "Isight"), '%(nr)s'),
                # Disable Search using EXALEAD
                (r"\s*(?P<exalead>[0-9]+) \[X\] Search using EXALEAD\nEnter selection:", '%(exalead)s\n\n'),
            ])

            # Directories
            cae_subdir = os.path.join(self.installdir, 'cae')
            sim_subdir = os.path.join(self.installdir, 'sim')
            qa.extend([
                (r"Default.*SIMULIA/EstProducts.*:", cae_subdir),
                (r"SIMULIA[0-9]*doc.*:", os.path.join(self.installdir, 'doc')),  # if docs are installed
                (r"SimulationServices.*:", sim_subdir),
                (r"Choose the CODE installation directory.*:\n.*\n\n.*:", sim_subdir),
                (r"SIMULIA/CAE.*:", cae_subdir),
                (r"location of your Abaqus services \(solvers\).*(\n.*){8}:\s*", sim_subdir),
                (r"Default.*SIMULIA/Commands\]:\s*", os.path.join(self.installdir, 'Commands')),
                (r"Default.*SIMULIA/CAE/plugins.*:\s*", os.path.join(self.installdir, 'plugins')),
                (r"Default.*SIMULIA/Isight.*:\s*", os.path.join(self.installdir, 'Isight')),
                (r"Default.*SIMULIA/fe-safe/.*:", os.path.join(self.installdir, 'fe-safe')),
                (r"Default.*SIMULIA/Tosca.*:", os.path.join(self.installdir, 'tosca')),
                # paths to STAR-CCM+, FLUENT are requested when Tosca is also installed;
                # these do not strictly need to be specified at installation time, so we don't
                (r"STAR-CCM.*\n((?!___).*\n)*?\nDefault \[\]:", ''),
                (r"FLUENT.*\n((?!___).*\n)*?\nDefault \[\]:", ''),
                (r"location of your existing ANSA installation.*(\n.*){8}:", ''),
                (r"FLUENT Path.*(\n.*){7}:", ''),
                (r"working directory to be used by Tosca Fluid\s*(\n.*)*Default \[/usr/temp\]:\s*", '/tmp'),
                # License server
                (r"License Server [0-9]+\s*(\n.*){3}:", 'abaqusfea'),  # bypass value for license server
                (r"License Server . \(redundant\)\s*(\n.*){3}:", ''),
                (r"License Server Configuration((?!___).*\n)*?" + nextstr, ''),
                (r"Please choose an action:", '1'),
            ])

            if LooseVersion(self.version) >= LooseVersion('2022') and installed_docs:
                java_root = get_software_root('Java')
                if java_root:
                    qa.extend([
                        (r"Please enter .*Java Runtime Environment.* path.(\n.*)+Default \[\]:", java_root),
                        (r"Please enter .*Java Runtime Environment.* path.(\n.*)+Default \[.+\]:", ''),
                    ])
                else:
                    raise EasyBuildError("Java is required for ABAQUS docs versions >= 2022, but it is missing")

            # Continue
            qa.append((nextstr, ''))

            run_shell_cmd('./StartTUI.sh', qa_patterns=qa, qa_wait_patterns=no_qa, qa_timeout=1000)
        else:
            change_dir(self.builddir)
            if self.cfg['install_cmd'] is None:
                self.cfg['install_cmd'] = "%s/%s-%s/setup" % (self.builddir, self.name, self.version.split('-')[0])
                self.cfg['install_cmd'] += " -replay %s" % self.replayfile
                if LooseVersion(self.version) < LooseVersion("6.13"):
                    self.cfg['install_cmd'] += " -nosystemcheck"
            super(EB_ABAQUS, self).install_step()

        if LooseVersion(self.version) >= LooseVersion('2016'):
            # also install hot fixes (if any)
            hotfixes = [src for src in self.src if 'CFA' in src['name']]
            if hotfixes:

                # first install Part_3DEXP_SimulationServices hotfix(es), if any
                hotfixes_3dexp = [src for src in self.src if 'CFA' in src['name'] and '3DEXP' in src['name']]
                if hotfixes_3dexp:
                    hotfix_dir = os.path.join(self.builddir, 'Part_3DEXP_SimulationServices.Linux64', '1', 'Software')
                    change_dir(hotfix_dir)

                    # SIMULIA_ComputeServices part
                    subdirs = glob.glob('HF_SIMULIA_ComputeServices.HF*.Linux64')
                    if len(subdirs) == 1:
                        subdir = subdirs[0]
                    else:
                        raise EasyBuildError("Failed to find expected subdir for hotfix: %s", subdirs)

                    cwd = change_dir(os.path.join(subdir, '1'))
                    qa = [
                        (r"Enter selection \(default: Next\):", ''),
                        (r"Choose the .*installation directory.*\n.*\n\n.*:", os.path.join(self.installdir, 'sim')),
                        (r"Enter selection \(default: Install\):", ''),
                    ]
                    run_shell_cmd('./StartTUI.sh', qa_patterns=qa, qa_wait_patterns=no_qa, qa_timeout=1000)

                    # F_CAASIMULIAComputeServicesBuildTime part
                    change_dir(cwd)
                    subdirs = glob.glob('HF_CAASIMULIAComputeServicesBuildTime.HF*.Linux64')
                    if len(subdirs) == 1:
                        subdir = subdirs[0]
                    else:
                        raise EasyBuildError("Failed to find expected subdir for hotfix: %s", subdirs)

                    cwd = change_dir(os.path.join(cwd, subdir, '1'))
                    run_shell_cmd('./StartTUI.sh', qa_patterns=qa, qa_wait_patterns=no_qa, qa_timeout=1000)
                    change_dir(cwd)

                # next install Part_SIMULIA_Abaqus_CAE hotfix (ABAQUS versions <= 2020)
                hotfix_dir = os.path.join(self.builddir, 'Part_SIMULIA_Abaqus_CAE.Linux64', '1', 'Software')
                if os.path.exists(hotfix_dir):
                    change_dir(hotfix_dir)

                    subdirs = glob.glob('SIMULIA_Abaqus_CAE.HF*.Linux64')
                    if len(subdirs) == 1:
                        subdir = subdirs[0]
                    else:
                        raise EasyBuildError("Failed to find expected subdir for hotfix: %s", subdirs)

                    cwd = change_dir(os.path.join(subdir, '1'))
                    qa = [
                        (r"Enter selection \(default: Next\):", ''),
                        (r"Choose the .*installation directory.*\n.*\n\n.*:", os.path.join(self.installdir, 'cae')),
                        (r"Enter selection \(default: Install\):", ''),
                        (r"\[1\] Continue\n(?:.|\n)*Please choose an action:", '1'),
                        (r"\[2\] Continue\n(?:.|\n)*Please choose an action:", '2'),
                    ]
                    no_qa = [r"Please be patient;  it will take a few minutes to complete\.\n(\.)*"]
                    run_shell_cmd('./StartTUI.sh', qa_patterns=qa, qa_wait_patterns=no_qa, qa_timeout=1000)
                    change_dir(cwd)

                # install SIMULIA Established Products hotfix (ABAQUS versions > 2020)
                hotfixes_estprd = [src for src in self.src if 'CFA' in src['name'] and 'EstPrd' in src['name']]
                if hotfixes_estprd:
                    hotfix_dir = os.path.join(self.builddir, 'Part_SIMULIA_EstPrd.Linux64', '1', 'Software')
                    change_dir(hotfix_dir)

                    subdirs = glob.glob('SIMULIA_EstPrd.HF*.Linux64')
                    if len(subdirs) == 1:
                        subdir = subdirs[0]
                    else:
                        raise EasyBuildError("Failed to find expected subdir for hotfix: %s", subdirs)

                    cwd = change_dir(os.path.join(subdir, '1'))
                    no_qa = [
                        r'___',
                        r'\.\.\.',
                        r'\(\d+[KM]B\)',
                    ]
                    qa = [
                        (r"Enter selection \(default: Next\):", ''),
                        (r"Choose the .*installation directory.*\n.*\n\n.*:", os.path.join(self.installdir, 'cae')),
                        (r"Enter selection \(default: Install\):", ''),
                        (r"The Abaqus commands directory.*:\n.*\n+Actions:\n.*\n_+\n\nPlease.*:", '1'),
                        (r"Enter selection \(default: Close\):", ''),
                    ]

                    run_shell_cmd('./StartTUI.sh', qa_patterns=qa, qa_wait_patterns=no_qa, qa_timeout=1000)
                    change_dir(cwd)

        # create 'abaqus' symlink for main command, which is not there anymore starting with ABAQUS 2022
        if LooseVersion(self.version) >= LooseVersion('2022'):
            commands_dir = os.path.join(self.installdir, 'Commands')
            abaqus_cmd = os.path.join(commands_dir, 'abaqus')
            if os.path.exists(abaqus_cmd):
                self.log.info("Main 'abaqus' command already found at %s, no need to create symbolic link", abaqus_cmd)
            else:
                abq_ver_cmd = os.path.join(commands_dir, 'abq%s' % self.version)
                self.log.info("Creating symbolic link 'abaqus' for main command %s", abq_ver_cmd)
                if os.path.exists(abq_ver_cmd):
                    cwd = change_dir(commands_dir)
                    symlink(os.path.basename(abq_ver_cmd), os.path.basename(abaqus_cmd))
                    change_dir(cwd)
                else:
                    raise EasyBuildError("Path to main command %s does not exist!", abq_ver_cmd)

    def sanity_check_step(self):
        """Custom sanity check for ABAQUS."""
        custom_paths = {
            'files': [os.path.join('Commands', 'abaqus')],
            'dirs': [],
        }
        custom_commands = []

        if LooseVersion(self.version) >= LooseVersion('2016'):
            custom_paths['dirs'].extend(['cae', 'Commands'])
            if LooseVersion(self.version) < LooseVersion('2020'):
                custom_paths['dirs'].extend(['sim'])
            # 'all' also check license server, but lmstat is usually not available
            custom_commands.append("abaqus information=system")
        else:
            verparts = self.version.split('-')[0].split('.')
            custom_paths['dirs'].append('%s-%s' % ('.'.join(verparts[0:2]), verparts[2]))
            custom_commands.append("abaqus information=all")

        if LooseVersion(self.version) >= LooseVersion('2020'):
            custom_paths['files'].append(os.path.join('cae', 'linux_a64', 'code', 'bin', 'abaqusstd'))
            if self.cfg['with_fe_safe']:
                custom_paths['files'].append(os.path.join('cae', 'linux_a64', 'code', 'bin', 'fe-safe'))

        if self.cfg['with_tosca']:
            custom_commands.append("ToscaPython.sh --help")

        super(EB_ABAQUS, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

    def make_module_extra(self):
        """Add LM_LICENSE_FILE path if specified"""
        txt = super(EB_ABAQUS, self).make_module_extra()
        license_file = os.getenv('EB_ABAQUS_LICENSE_FILE', None)
        if license_file is not None:
            txt += self.module_generator.prepend_paths('ABAQUSLM_LICENSE_FILE', [license_file], allow_abs=True)

        return txt
