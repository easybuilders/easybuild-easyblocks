##
# Copyright 2009-2024 Ghent University
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
EasyBuild support for building and installing RepeatModeler, implemented as an easyblock

@author: Jasper Grimm (UoY)
"""

import os

from easybuild.easyblocks.generic.tarball import Tarball
from easybuild.easyblocks.perl import get_site_suffix
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import change_dir, patch_perl_script_autoflush
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_cmd_qa


def get_dep_path(dep_name, rel_path, log, optional):
    """
    Check for dependency, raise error if it's not available (unless optional=True is used).
    Return full path to specified relative path in dependency installation directory,
    return None if optional dependency is not found.
    """

    dep_root = get_software_root(dep_name)
    if dep_root:
        dep = os.path.join(dep_root, rel_path)
        return dep
    elif optional:
        log.info("Optional dependency not found: %s" % dep_name)
        return ''
    else:
        raise EasyBuildError("Missing required dependency: %s" % dep_name)


class EB_RepeatModeler(Tarball):
    """Support for building/installing RepeatModeler."""

    def install_step(self):
        """Custom install procedure for RepeatModeler."""
        super(EB_RepeatModeler, self).install_step()

        # Required dependencies, and bin path relative to software root
        required_deps = {
            'CD-HIT': 'bin',
            'Kent_tools': 'bin',
            'Perl': os.path.join('bin', 'perl'),
            'RECON': 'bin',
            'RepeatMasker': '',
            'RepeatScout': '',
            'TRF': os.path.join('bin', 'trf'),
        }

        # Search engines, and bin path relative to software root
        search_engines = {
            'ABBlast': 'bin',
            'RMBlast': 'bin',
            'WUBlast': 'bin',
        }

        # Optional dependencies for LTR pipeline, and bin path relative to software root
        optional_LTR_deps = {
            'GenomeTools': 'bin',
            'LTR_retriever': '',
            'MAFFT': 'bin',
            'TWL-NINJA': 'bin',
        }

        for dep, path in required_deps.items():
            required_deps[dep] = get_dep_path(dep, path, log=self.log, optional=False)

        for dep, path in search_engines.items():
            search_engines[dep] = get_dep_path(dep, path, log=self.log, optional=True)

        for dep, path in optional_LTR_deps.items():
            optional_LTR_deps[dep] = get_dep_path(dep, path, log=self.log, optional=True)

        # Check at least one search engine is present, and not both ABBlast/WUBlast
        if not any(search_engines.values()):
            raise EasyBuildError("At least one search engine must be specified: RMBlast, ABBlast, WUBlast")
        elif search_engines['ABBlast'] and search_engines['WUBlast']:
            raise EasyBuildError("Cannot specify both ABBlast and WUBlast")

        # Check if all LTR Pipeline dependencies present
        if all(optional_LTR_deps.values()):
            self.log.info("All LTR pipeline dependencies found, enabling LTR support")
            with_LTR = 'y'
        else:
            self.log.info("Not all LTR pipeline dependencies found, disabling LTR support")
            with_LTR = 'n'

        # Map search engine to configuration option
        search_engine_map = {
            'ABBlast': '2',
            'RMBlast': '1',
            'WUBlast': '2',
        }

        # List of search engines to use (mapped)
        mapped_engines = [search_engine_map[k] for k, v in search_engines.items() if v] + ['3']

        change_dir(self.installdir)

        # Fix perl shebang in configure script (#!/usr/local/bin/perl)
        orig_fix_perl_shebang_for = self.cfg['fix_perl_shebang_for']
        self.cfg['fix_perl_shebang_for'] = [os.path.join(self.installdir, 'configure')]
        self.fix_shebang()
        self.cfg['fix_perl_shebang_for'] = orig_fix_perl_shebang_for

        patch_perl_script_autoflush('configure')

        qa = {
            '<PRESS ENTER TO CONTINUE>': '',
        }
        std_qa = {
            r'\*\*PERL INSTALLATION PATH\*\*\n\n[^*]*\n+Enter path.*:\s*': required_deps['Perl'],
            r'UCSCTOOLS_DIR.*:\s*': required_deps['Kent_tools'],
            r'LTR_RETRIEVER_DIR.*:\s*': optional_LTR_deps['LTR_retriever'],
            r'RMBLAST_DIR.*:\s*': search_engines['RMBlast'],
            r'ABBLAST_DIR.*:\s*': search_engines['ABBlast'] or search_engines['WUBlast'],
            # Configure first engine
            r'.*(\[ Un\-configured \]\n.*){2}\n.*\n+Enter Selection\:\s*': mapped_engines[0],
            # Configure second engine if multiple specified, otherwise skip
            r'.*(\[ Un\-configured \]\n.*\[ Configured \]|\[ Configured \]\n.*\[ Un-configured \])'
            r'\n\n.*\n+Enter Selection\:\s*': mapped_engines[1],
            # All engines configured
            r'.*(\[ Configured \]\n.*){2}\n.*\n+Enter Selection\:\s*': '3',
            # LTR
            r'LTR.*\[optional](.*\n)*of analysis \[y] or n\?\:\s*': with_LTR,
        }

        cmdopts = ' ' + ' '.join([
            '-trf_prgm "%(TRF)s"',
            '-repeatmasker_dir "%(RepeatMasker)s"',
            '-rscout_dir "%(RepeatScout)s"',
            '-recon_dir "%(RECON)s"',
            '-ucsctools_dir "%(Kent_tools)s"',
            '-cdhit_dir "%(CD-HIT)s"',
        ]) % required_deps

        if with_LTR:
            cmdopts += ' ' + ' '.join([
                '-mafft_dir "%(MAFFT)s"',
                '-genometools_dir "%(GenomeTools)s"',
                '-ltr_retriever_dir "%(LTR_retriever)s"',
                '-ninja_dir "%(TWL-NINJA)s"',
            ]) % optional_LTR_deps

        cmd = "perl ./configure" + cmdopts
        run_cmd_qa(cmd, qa, std_qa=std_qa, log_all=True, simple=True, log_ok=True, maxhits=100)

    def sanity_check_step(self):
        """Custom sanity check for RepeatModeler."""

        custom_paths = {
            'files': ['BuildDatabase', 'RepeatClassifier', 'RepeatModeler', 'RepeatUtil.pm'],
            'dirs': ['Libraries', 'Matrices', 'util'],
        }

        custom_commands = [("RepeatModeler -help 2>&1 | grep 'RepeatModeler - Model repetitive DNA'", '')]

        super(EB_RepeatModeler, self).sanity_check_step(custom_commands=custom_commands, custom_paths=custom_paths)

    def make_module_req_guess(self):
        """Custom guesses for path-like environment variables for RepeatModelerConfig."""
        guesses = super(EB_RepeatModeler, self).make_module_req_guess()

        guesses.update({
            'PATH': [''],
            'PERL5LIB': [get_site_suffix('sitelib')],
        })

        return guesses
