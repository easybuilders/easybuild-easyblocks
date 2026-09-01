##
# Copyright 2009-2026 Ghent University
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
EasyBuild easyblock for PsN installation.
This easyblock installs PsN without running upstream bin/setup.pl.
It is intended to be used as the final extension in a Bundle where the
required CPAN modules are installed as PerlModule extensions first.

@author: Pavel Tomanek (Inuits/Ugent) with help of ChatGPT5.5
"""

import os
import re
import stat

from easybuild.framework.easyconfig import CUSTOM, MANDATORY
from easybuild.framework.extensioneasyblock import ExtensionEasyBlock
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import adjust_permissions, copy_dir, mkdir, read_file, remove_dir, remove_file
from easybuild.tools.filetools import symlink, which, write_file
from easybuild.tools.modules import get_software_version

PSN_UTILITIES = [
    'bootstrap',
    'cdd',
    'execute',
    'llp',
    'scm',
    'sumo',
    'sse',
    'update_inits',
    'update',
    'npc',
    'vpc',
    'pind',
    'nonpb',
    'extended_grid',
    'psn',
    'psn_options',
    'psn_clean',
    'runrecord',
    'mcmp',
    'lasso',
    'mimp',
    'xv_scm',
    'parallel_retries',
    'boot_scm',
    'gls',
    'simeval',
    'frem',
    'randtest',
    'linearize',
    'crossval',
    'pvar',
    'nca',
    'proseval',
    'sir',
    'rawresults',
    'precond',
    'covmat',
    'nmoutput2so',
    'benchmark',
    'npfit',
    'resmod',
    'cddsimeval',
    'qa',
    'transform',
    'boot_randtest',
    'monitor',
    'scmplus',
    'scmreport',
    'm1find',
    'pack',
]


class EB_PsN(ExtensionEasyBlock):
    """Install PsN as an EasyBuild extension without running setup.pl."""

    @staticmethod
    def extra_options(extra_vars=None):
        """Define custom easyconfig parameters for PsN."""
        extra_vars = ExtensionEasyBlock.extra_options(extra_vars)
        extra_vars.update({
            'perllib': [
                None,
                'Perl library subdirectory where PsN should be installed',
                MANDATORY,
            ],
            'nm_versions': [
                None,
                'Optional list of PsN nm_versions entries, e.g. default=nmfe76,7.6. '
                'If unset, entries are derived from the loaded NONMEM module.',
                CUSTOM,
            ],
        })
        return extra_vars

    def configure_step(self):
        """No configure step for PsN."""
        pass

    def build_step(self):
        """No build step for PsN."""
        pass

    def install_step(self):
        """Install PsN when this easyblock is used as a stand-alone easyblock."""
        self._install_psn(self.start_dir)

    def install_extension(self, unpack_src=True):
        """Install PsN when used as an extension in a Bundle."""
        super().install_extension(unpack_src=unpack_src)
        self._install_psn(self.start_dir)

    def sanity_check_step(self):
        """Check whether PsN was installed correctly."""
        psn_ver = self.version.replace('.', '_')
        psndir = os.path.join(self.cfg['perllib'], 'PsN_%s' % psn_ver)

        custom_paths = {
            'files': [
                os.path.join('bin', 'psn-%s' % self.version),
                os.path.join('bin', 'psn'),
                os.path.join(psndir, 'psn.conf'),
            ],
            'dirs': [],
        }

        return super().sanity_check_step(custom_paths=custom_paths)

    def _determine_nm_versions(self):
        """Derive PsN nm_versions entries from the loaded NONMEM module."""
        nonmem_version = get_software_version('NONMEM')

        if not nonmem_version:
            raise EasyBuildError(
                "Could not determine the version of the loaded NONMEM dependency. "
                "Either add NONMEM as a dependency or specify 'nm_versions' explicitly."
            )

        parts = nonmem_version.split('.')
        if len(parts) < 2:
            raise EasyBuildError("Unexpected NONMEM version format: %s", nonmem_version)

        major = parts[0]
        minor = parts[1]
        patch = parts[2] if len(parts) > 2 else '0'

        psn_nm_version = '%s.%s' % (major, minor)
        nmfe_cmd = 'nmfe%s%s' % (major, minor)
        nm_alias = 'nm%s%s%s' % (major, minor, patch)

        nmfe_path = which(nmfe_cmd)

        if not nmfe_path:
            raise EasyBuildError("Could not find NONMEM executable '%s' in PATH", nmfe_cmd)

        self.log.info("Detected NONMEM version: %s", nonmem_version)
        self.log.info("Detected NONMEM executable for PsN: %s", nmfe_path)
        self.log.info("Using PsN NONMEM version string: %s", psn_nm_version)
        self.log.info("Using PsN NONMEM alias: %s", nm_alias)

        return [
            'default=%s,%s' % (nmfe_cmd, psn_nm_version),
            '%s=%s,%s' % (nm_alias, nmfe_cmd, psn_nm_version),
        ]

    def _install_psn(self, srcdir):
        """Install PsN Perl library, scripts, symlinks, and config file."""
        perllib = self.cfg['perllib']
        if not perllib:
            raise EasyBuildError("Missing required easyconfig parameter 'perllib'")

        nm_versions = self.cfg['nm_versions'] or self._determine_nm_versions()

        perl = which('perl')
        if not perl:
            raise EasyBuildError("Could not find perl in PATH")

        bindir = os.path.join(self.installdir, 'bin')
        libbase = os.path.join(self.installdir, perllib)
        psn_ver = self.version.replace('.', '_')
        psndir = os.path.join(libbase, 'PsN_%s' % psn_ver)

        self.log.info("Installing PsN from source directory: %s", srcdir)
        self.log.info("Installing PsN scripts into: %s", bindir)
        self.log.info("Installing PsN Perl library into: %s", psndir)

        mkdir(bindir, parents=True)
        mkdir(libbase, parents=True)

        self._copy_psn_lib(srcdir, psndir)
        self._install_utilities(srcdir, perl, psndir, bindir)
        self._create_psn_conf(psndir, perl, nm_versions)

    def _copy_psn_lib(self, srcdir, psndir):
        """Copy upstream lib/ into the versioned PsN Perl library directory."""
        lib_src = os.path.join(srcdir, 'lib')

        if not os.path.isdir(lib_src):
            raise EasyBuildError("Could not find PsN lib directory: %s", lib_src)

        remove_dir(psndir)
        copy_dir(lib_src, psndir)

    def _install_utilities(self, srcdir, perl, psndir, bindir):
        """Install PsN command-line utilities."""

        for util in PSN_UTILITIES:
            self._install_utility(srcdir, util, perl, psndir, bindir)

    def _install_utility(self, srcdir, util, perl, psndir, bindir):
        """Install one versioned PsN utility and create an unversioned symlink."""
        src = os.path.join(srcdir, 'bin', util)

        if not os.path.isfile(src):
            raise EasyBuildError("Could not find PsN utility script: %s", src)

        versioned = os.path.join(bindir, '%s-%s' % (util, self.version))
        unversioned = os.path.join(bindir, util)

        content = read_file(src, mode='rb')

        marker = b'# Everything above this line will be replaced #'
        if marker not in content:
            raise EasyBuildError("Marker line not found in PsN utility script: %s", src)

        body = content.split(marker, 1)[1]
        header = '\n'.join([
            '#!%s' % perl,
            "use lib '%s';" % psndir,
            "use lib '%s';" % os.path.dirname(psndir),
            '',
            '# Everything above this line was entered by the EasyBuild PsN easyblock #',
            '',
        ]).encode('utf-8')

        write_file(versioned, header + body)

        adjust_permissions(
            versioned,
            stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH,
            recursive=False,
        )

        remove_file(unversioned)
        symlink(os.path.basename(versioned), unversioned, use_abspath_source=False)

    def _create_psn_conf(self, psndir, perl, nm_versions):
        """Create psn.conf from psn.conf_template and inject EB-controlled values."""
        template = os.path.join(psndir, 'psn.conf_template')
        conf = os.path.join(psndir, 'psn.conf')

        if not os.path.isfile(template):
            raise EasyBuildError("Could not find PsN config template: %s", template)

        txt = read_file(template)

        txt = self._set_global_key(txt, 'perl', perl)

        rbin = which('R')
        if rbin:
            txt = self._set_global_key(txt, 'R', rbin)

        nm_lines = []
        for entry in nm_versions:
            if '=' not in entry:
                raise EasyBuildError(
                    "Invalid nm_versions entry '%s'; expected format name=cmd,version",
                    entry
                )
            nm_lines.append(entry)

        txt = self._replace_section(txt, 'nm_versions', nm_lines)

        write_file(conf, txt)

        self.log.info("Created PsN config file: %s", conf)

    def _set_global_key(self, txt, key, value):
        """Set or prepend a global Config::Tiny-style key."""
        pattern = r'(?m)^%s\s*=.*$' % re.escape(key)
        replacement = '%s=%s' % (key, value)

        if re.search(pattern, txt):
            return re.sub(pattern, replacement, txt, count=1)

        return replacement + '\n' + txt

    def _replace_section(self, txt, section, lines):
        """Replace or append an INI-style section."""
        replacement = '[%s]\n%s\n\n' % (section, '\n'.join(lines))
        pattern = r'(?ms)^\[%s\]\s*\n.*?(?=^\[|\Z)' % re.escape(section)

        if re.search(pattern, txt):
            return re.sub(pattern, replacement, txt, count=1)

        if not txt.endswith('\n'):
            txt += '\n'

        return txt + '\n' + replacement
