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
EasyBuild support for building and installing RepeatModeler, implemented as an easyblock

@author: Jasper Grimm (UoY)
"""

from distutils.version import LooseVersion
import os, re

from easybuild.easyblocks.generic.tarball import Tarball
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import change_dir, patch_perl_script_autoflush
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.run import run_cmd_qa

def get_dep_path(dep_name, rel_path, log, optional):
    """Check for dependency. If it exists return full path, else empty string"""

    dep_root = get_software_root(dep_name)
    if dep_root:
        dep = os.path.join(dep_root, *rel_path)
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
            'Perl': ['bin', 'perl'],
            'TRF': ['bin', 'trf'],
            'RECON': ['bin'],
            'RepeatMasker': [],
            'RepeatScout': [],
            'Kent_tools': ['bin'],
            'CD-HIT': ['bin'],
        }

        # Search engines, and bin path relative to software root
        search_engines = {
            'RMBlast': ['bin'],
            'ABBlast': ['bin'],
            'WUBlast': ['bin'],
        }

        # Optional dependencies for LTR pipeline, and bin path relative to software root
        optional_LTR_deps = {
            'MAFFT': ['bin'],
            'GenomeTools': ['bin'],
            'LTR_retriever': [],
            'NINJA': ['bin'],
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
            'RMBlast': '1',
            'ABBlast': '2',
            'WUBlast': '2',
        }

        # List of search engines to use (mapped)
        mapped_engines = [search_engine_map[k] for k, v in search_engines.items() if v] + ['3']

        change_dir(self.installdir)

        # Fix perl shebang in configure script (#!/usr/local/bin/perl)
        shebang_re = re.compile(r'^#!/.*perl')
        new_shebang = "#!/usr/bin/env perl"
        try:
            configure_script = os.path.join(self.installdir, 'configure')
            txt = open(configure_script, 'r').read()
            txt = shebang_re.sub(new_shebang, txt)
            txt = shebang_re.sub(new_shebang, txt)
        except IOError as err:
            raise EasyBuildError("Failed to patch shebang header in %s: %s", configure_script, txt)

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

        cmdopts = ' -trf_prgm "%s" -repeatmasker_dir "%s" -rscout_dir "%s" -recon_dir "%s" -ucsctools_dir "%s" ' \
            '-cdhit_dir "%s"' % tuple([required_deps[x] for x in ['TRF', 'RepeatMasker', 'RepeatScout', 'RECON',
                                                                 'Kent_tools', 'CD-HIT']])

        if with_LTR:
            cmdopts += ' -mafft_dir "%s" -genometools_dir "%s" -ltr_retriever_dir "%s" -ninja_dir "%s"' % \
                tuple(optional_LTR_deps.values())

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

        perlver = get_software_version('Perl')
        guesses.update({
            'PATH': [''],
            'PERL5LIB': [os.path.join('lib', 'perl5', 'site_perl', perlver)],
        })

        return guesses
