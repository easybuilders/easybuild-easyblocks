##
# Copyright 2009-2021 Ghent University
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
from distutils.version import LooseVersion
import glob
import os

from easybuild.easyblocks.generic.binary import Binary
from easybuild.framework.easyblock import EasyBlock
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.environment import setvar
from easybuild.tools.filetools import change_dir, write_file
from easybuild.tools.run import run_cmd_qa
from easybuild.tools.py2vs3 import OrderedDict


class EB_ABAQUS(Binary):
    """Support for installing ABAQUS."""

    @staticmethod
    def extra_options():
        extra_vars = {
            'with_tosca': [None, "Enable installation of Tosca (if None: auto-enable for ABAQUS >= 2020)", CUSTOM],
        }
        return Binary.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        """Initialisation of custom class variables for ABAQUS."""
        super(EB_ABAQUS, self).__init__(*args, **kwargs)
        self.replayfile = None

        if self.cfg['with_tosca'] is None and LooseVersion(self.version) >= LooseVersion('2020'):
            self.log.info("Auto-enabling installation of Tosca component for ABAQUS versions >= 2020")
            self.cfg['with_tosca'] = True

    def extract_step(self):
        """Use default extraction procedure instead of the one for the Binary easyblock."""
        EasyBlock.extract_step(self)

    def configure_step(self):
        """Configure ABAQUS installation."""
        if LooseVersion(self.version) >= LooseVersion('2016'):
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
            qa = {
                "Enter selection (default: Install):": '',
                "Enter selection (default: Close):": '',
            }
            no_qa = [
                '___',
                r"\(\d+\s*[KM]B\)",
            ]

            # Match string for continuing on with the selected items
            nextstr = r"Enter selection \(default: Next\):\s*"

            # Allow for selection or deselection of components from lines of the form:
            #   5 [*] Tosca Fluid
            # This uses nextstr to make sure we only match the latest output in the Q&A process;
            # negative lookahead (?!___) is used to exclude ___...___ lines, to avoid matching across questions
            selectionstr = r"\s*(?P<nr>[-0-9]+) %%s %%s[ \w]*\n((?!%s)(?!___)[\S ]*\n)*%s$" % (nextstr, nextstr)

            # ensure question patterns are considered in order by using an OrderedDict instance,
            # rather than a regular dictionary (where there's no guarantee on key order in general)
            std_qa = OrderedDict()

            # Enable Extended Product Documentation
            std_qa[selectionstr % (r"\[ \]", "Extended Product Documentation")] = "%(nr)s"
            # Enable Abaqus CAE (docs)
            std_qa[selectionstr % (r"\[ \]", "Abaqus CAE")] = "%(nr)s"

            # Disable/enable Tosca
            if self.cfg['with_tosca']:
                std_qa[selectionstr % (r"\[\ \]", "Tosca")] = "%(nr)s"
            else:
                std_qa[selectionstr % (r"\[\*\]", "Tosca")] = "%(nr)s"

            # Disable Isight
            std_qa[selectionstr % (r"\[\*\]", "Isight")] = "%(nr)s"
            # Disable Search using EXALEAD
            std_qa[r"\s*(?P<exalead>[0-9]+) \[X\] Search using EXALEAD\nEnter selection:"] = '%(exalead)s\n\n'

            # Directories
            cae_subdir = os.path.join(self.installdir, 'cae')
            sim_subdir = os.path.join(self.installdir, 'sim')
            std_qa[r"Default.*SIMULIA/EstProducts.*:"] = cae_subdir
            std_qa[r"SIMULIA[0-9]*doc.*:"] = os.path.join(self.installdir, 'doc')
            std_qa[r"SimulationServices.*:"] = sim_subdir
            std_qa[r"Choose the CODE installation directory.*:\n.*\n\n.*:"] = sim_subdir
            std_qa[r"SIMULIA/CAE.*:"] = cae_subdir
            std_qa[r"location of your Abaqus services \(solvers\).*(\n.*){8}:\s*"] = sim_subdir
            std_qa[r"Default.*SIMULIA/Commands\]:\s*"] = os.path.join(self.installdir, 'Commands')
            std_qa[r"Default.*SIMULIA/CAE/plugins.*:\s*"] = os.path.join(self.installdir, 'plugins')
            std_qa[r"Default.*SIMULIA/Isight.*:\s*"] = os.path.join(self.installdir, 'Isight')
            std_qa[r"Default.*SIMULIA/fe-safe/.*:"] = os.path.join(self.installdir, 'fe-safe')
            std_qa[r"Default.*SIMULIA/Tosca.*:"] = os.path.join(self.installdir, 'tosca')

            # paths to STAR-CCM+, FLUENT are requested when Tosca is also installed;
            # these do not strictly need to be specified at installation time, so we don't
            std_qa[r"STAR-CCM.*\n((?!___)[\S ]*\n)*\nDefault \[\]:"] = ''
            std_qa[r"FLUENT.*\n((?!___)[\S ]*\n)*\nDefault \[\]:"] = ''

            std_qa[r"location of your existing ANSA installation.*(\n.*){8}:"] = ''
            std_qa[r"FLUENT Path.*(\n.*){7}:"] = ''
            std_qa[r"working directory to be used by Tosca Fluid\s*(\n.*)*Default \[/usr/temp\]:\s*"] = '/tmp'

            # License server
            std_qa[r"License Server [0-9]+\s*(\n.*){3}:"] = 'abaqusfea'  # bypass value for license server
            std_qa[r"License Server . \(redundant\)\s*(\n.*){3}:"] = ''
            std_qa[r"License Server Configuration((?!___).*\n)*" + nextstr] = ''

            std_qa[r"Please choose an action:"] = '1'

            # Continue
            std_qa[nextstr] = ''

            run_cmd_qa('./StartTUI.sh', qa, no_qa=no_qa, std_qa=std_qa, log_all=True, simple=True, maxhits=100)
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
                    std_qa = OrderedDict()
                    std_qa[r"Enter selection \(default: Next\):"] = ''
                    std_qa["Choose the .*installation directory.*\n.*\n\n.*:"] = os.path.join(self.installdir, 'sim')
                    std_qa[r"Enter selection \(default: Install\):"] = ''
                    run_cmd_qa('./StartTUI.sh', {}, std_qa=std_qa, log_all=True, simple=True, maxhits=100)

                    # F_CAASIMULIAComputeServicesBuildTime part
                    change_dir(cwd)
                    subdirs = glob.glob('HF_CAASIMULIAComputeServicesBuildTime.HF*.Linux64')
                    if len(subdirs) == 1:
                        subdir = subdirs[0]
                    else:
                        raise EasyBuildError("Failed to find expected subdir for hotfix: %s", subdirs)

                    cwd = change_dir(os.path.join(cwd, subdir, '1'))
                    run_cmd_qa('./StartTUI.sh', {}, std_qa=std_qa, log_all=True, simple=True, maxhits=100)
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
                    std_qa = OrderedDict()
                    std_qa[r"Enter selection \(default: Next\):"] = ''
                    std_qa["Choose the .*installation directory.*\n.*\n\n.*:"] = os.path.join(self.installdir, 'cae')
                    std_qa[r"Enter selection \(default: Install\):"] = ''
                    std_qa[r"\[1\] Continue\n(?:.|\n)*Please choose an action:"] = '1'
                    std_qa[r"\[2\] Continue\n(?:.|\n)*Please choose an action:"] = '2'
                    no_qa = [r"Please be patient;  it will take a few minutes to complete\.\n(\.)*"]
                    run_cmd_qa('./StartTUI.sh', {}, no_qa=no_qa, std_qa=std_qa, log_all=True, simple=True, maxhits=100)
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
                        '___',
                        '...',
                        r'\(\d+[KM]B\)',
                    ]
                    std_qa = OrderedDict()
                    std_qa[r"Enter selection \(default: Next\):"] = ''
                    std_qa["Choose the .*installation directory.*\n.*\n\n.*:"] = os.path.join(self.installdir, 'cae')
                    std_qa[r"Enter selection \(default: Install\):"] = ''
                    std_qa[r"The Abaqus commands directory.*:\n.*\n+Actions:\n.*\n_+\n\nPlease.*:"] = '1'
                    std_qa[r"Enter selection \(default: Close\):"] = ''

                    run_cmd_qa('./StartTUI.sh', {}, no_qa=no_qa, std_qa=std_qa, log_all=True, simple=True, maxhits=100)
                    change_dir(cwd)

    def sanity_check_step(self):
        """Custom sanity check for ABAQUS."""
        custom_paths = {
            'files': [os.path.join('Commands', 'abaqus')],
            'dirs': [],
        }
        custom_commands = []

        if LooseVersion(self.version) >= LooseVersion('2016'):
            custom_paths['dirs'].extend(['cae', 'Commands', 'doc'])
            if LooseVersion(self.version) < LooseVersion('2020'):
                custom_paths['dirs'].extend(['sim'])
            # 'all' also check license server, but lmstat is usually not available
            custom_commands.append("abaqus information=system")
        else:
            verparts = self.version.split('-')[0].split('.')
            custom_paths['dirs'].append('%s-%s' % ('.'.join(verparts[0:2]), verparts[2]))
            custom_commands.append("abaqus information=all")

        if self.cfg['with_tosca']:
            custom_commands.append("ToscaPython.sh --help")

        super(EB_ABAQUS, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

    def make_module_req_guess(self):
        """Update $PATH guesses for ABAQUS."""
        guesses = super(EB_ABAQUS, self).make_module_req_guess()

        path_subdirs = ['Commands']
        if self.cfg['with_tosca']:
            path_subdirs.append(os.path.join('cae', 'linux_a64', 'code', 'command'))

        guesses.update({
            'PATH': path_subdirs,
        })

        return guesses
