#!/usr/bin/env python
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
EasyBuild support for installing Cargo packages (Rust lang package system)

@author: Mikael Oehman (Chalmers University of Technology)
@author: Alex Domingo (Vrije Universiteit Brussel)
@author: Alexander Grund (TU Dresden)
"""

import os
import re
from collections import defaultdict

import easybuild.tools.environment as env
import easybuild.tools.systemtools as systemtools
from easybuild.tools.build_log import EasyBuildError, print_warning
from easybuild.framework.easyconfig import CUSTOM
from easybuild.framework.extensioneasyblock import ExtensionEasyBlock
from easybuild.tools.filetools import extract_file
from easybuild.tools.run import run_cmd
from easybuild.tools.config import build_option
from easybuild.tools.filetools import compute_checksum, mkdir, move_file, read_file, write_file, CHECKSUM_TYPE_SHA256
from easybuild.tools.toolchain.compiler import OPTARCH_GENERIC

CRATESIO_SOURCE = "https://crates.io/api/v1/crates"

CONFIG_TOML_SOURCE_VENDOR = """
[source.vendored-sources]
directory = "{vendor_dir}"

[source.crates-io]
replace-with = "vendored-sources"

"""

CONFIG_TOML_SOURCE_GIT = """
[source."{url}?rev={rev}"]
git = "{url}"
rev = "{rev}"
replace-with = "vendored-sources"
"""

CONFIG_TOML_SOURCE_GIT_WORKSPACE = """
[source."real-{url}?rev={rev}"]
directory = "{workspace_dir}"

[source."{url}?rev={rev}"]
git = "{url}"
rev = "{rev}"
replace-with = "real-{url}?rev={rev}"

"""

CARGO_CHECKSUM_JSON = '{{"files": {{}}, "package": "{checksum}"}}'


def get_workspace_members(crate_dir):
    """Find all members of a cargo workspace in crate_dir.

    (Minimally) parse the Cargo.toml file.
    If it is a workspace return all members (subfolder names).
    Otherwise return None.
    """
    cargo_toml = os.path.join(crate_dir, 'Cargo.toml')

    # We are looking for this:
    # [workspace]
    # members = [
    # "reqwest-middleware",
    # "reqwest-tracing",
    # "reqwest-retry",
    # ]

    lines = [line.strip() for line in read_file(cargo_toml).splitlines()]
    try:
        start_idx = lines.index('[workspace]')
    except ValueError:
        return None
    # Find "members = [" and concatenate the value, stop at end of section or file
    member_str = None
    for line in lines[start_idx + 1:]:
        if line.startswith('#'):
            continue  # Skip comments
        if re.match(r'\[\w+\]', line):
            break
        if member_str is None:
            m = re.match(r'members\s+=\s+\[', line)
            if m:
                member_str = line[m.end():]
        elif line.endswith(']'):
            member_str += line[:-1].strip()
            break
        else:
            member_str += line
    # Split at commas after removing possibly trailing ones and remove the quotes
    members = [member.strip().strip('"') for member in member_str.rstrip(',').split(',')]
    # Sanity check that we didn't pick up anything unexpected
    invalid_members = [member for member in members if not re.match(r'(\w|-)+', member)]
    if invalid_members:
        raise EasyBuildError('Failed to parse %s: Found seemingly invalid members: %s',
                             cargo_toml, ', '.join(invalid_members))
    return [os.path.join(crate_dir, m) for m in members]


def get_checksum(src, log):
    """Get the checksum from an extracted source"""
    checksum = src['checksum']
    if isinstance(checksum, dict):
        try:
            checksum = checksum[src['name']]
        except KeyError:
            log.warning('No checksum for %s in %s', checksum, src['name'])
            checksum = None
    return checksum


class Cargo(ExtensionEasyBlock):
    """Support for installing Cargo packages (Rust)"""

    BRANCH_MISSING = object()  # Used when branch information was not specified

    @staticmethod
    def extra_options(extra_vars=None):
        """Define extra easyconfig parameters specific to Cargo"""
        extra_vars = ExtensionEasyBlock.extra_options(extra_vars)
        extra_vars.update({
            'enable_tests': [True, "Enable building of tests", CUSTOM],
            'offline': [True, "Build offline", CUSTOM],
            'lto': [None, "Override default LTO flag ('fat', 'thin', 'off')", CUSTOM],
            'crates': [[], "List of (crate, version, [repo, rev, branch]) tuples to use. branch can be None", CUSTOM],
        })

        return extra_vars

    @staticmethod
    def crate_src_filename(pkg_name, pkg_version, _url=None, rev=None, _branch=None):
        """Crate tarball filename based on package name, version and optionally git revision"""
        filename = [pkg_name, pkg_version]
        filename_ext = '.tar.gz'

        if rev is not None:
            # sources from a git repo
            filename.append(rev[:8])  # append short commit hash
            filename_ext = '.tar.xz'  # use a reproducible archive format

        return '-'.join(filename) + filename_ext

    @staticmethod
    def crate_download_filename(pkg_name, pkg_version):
        """Crate download filename based on package name and version"""
        return "{0}/{1}/download".format(pkg_name, pkg_version)

    def rustc_optarch(self):
        """Determines what architecture to target.
        Translates GENERIC optarch, and respects rustc specific optarch.
        General optarchs are ignored as there is no direct translation.
        """
        if systemtools.X86_64 == systemtools.get_cpu_architecture():
            generic = '-C target-cpu=x86-64'
        else:
            generic = '-C target-cpu=generic'

        optimal = '-C target-cpu=native'

        optarch = build_option('optarch')
        if optarch:
            if isinstance(optarch, dict):
                if 'rustc' in optarch:
                    rust_optarch = optarch['rustc']
                    if rust_optarch == OPTARCH_GENERIC:
                        return generic
                    else:
                        return '-' + rust_optarch
                self.log.info("no rustc information in the optarch dict, so using %s" % optimal)
            elif optarch == OPTARCH_GENERIC:
                return generic
            else:
                self.log.warning("optarch is ignored as there is no translation for rustc, so using %s" % optimal)
        return optimal

    def __init__(self, *args, **kwargs):
        """Constructor for Cargo easyblock."""
        super(Cargo, self).__init__(*args, **kwargs)
        self.cargo_home = os.path.join(self.builddir, '.cargo')
        self.set_cargo_vars()

        # Populate sources from "crates" list of tuples
        sources = []
        for crate_info in self.crates:
            if len(crate_info) == 2:
                sources.append({
                    'download_filename': self.crate_download_filename(*crate_info),
                    'filename': self.crate_src_filename(*crate_info),
                    'source_urls': [CRATESIO_SOURCE],
                    'alt_location': 'crates.io',
                })
            else:
                crate, version, repo, rev = crate_info[0:4]  # Ignore branch info
                url, repo_name = repo.rsplit('/', maxsplit=1)
                if repo_name.endswith('.git'):
                    repo_name = repo_name[:-4]
                sources.append({
                    'git_config': {'url': url, 'repo_name': repo_name, 'commit': rev},
                    'filename': self.crate_src_filename(crate, version, rev=rev),
                })

        # copy EasyConfig instance before we make changes to it
        self.cfg = self.cfg.copy()

        self.cfg.update('sources', sources)

    def set_cargo_vars(self):
        """Set environment variables for Rust compilation and Cargo"""
        env.setvar('CARGO_HOME', self.cargo_home)
        env.setvar('RUSTC', 'rustc')
        env.setvar('RUSTDOC', 'rustdoc')
        env.setvar('RUSTFMT', 'rustfmt')
        env.setvar('RUSTFLAGS', self.rustc_optarch())
        env.setvar('RUST_LOG', 'DEBUG')
        env.setvar('RUST_BACKTRACE', '1')

    @property
    def crates(self):
        """Return the crates as defined in the EasyConfig"""
        return self.cfg['crates']

    def load_module(self, *args, **kwargs):
        """(Re)set environment variables after loading module file.

        Required here to ensure the variables are defined for stand-alone installations and extensions,
        because the environment is reset to the initial environment right before loading the module.
        """

        super(Cargo, self).load_module(*args, **kwargs)
        self.set_cargo_vars()

    def extract_step(self):
        """
        Unpack the source files and populate them with required .cargo-checksum.json if offline
        """
        self.vendor_dir = os.path.join(self.builddir, 'easybuild_vendor')
        mkdir(self.vendor_dir)
        # Sources from git repositories might contain multiple crates/folders in a so-called "workspace".
        # If we put such a workspace into the vendor folder, cargo fails with
        # "found a virtual manifest at [...]Cargo.toml instead of a package manifest".
        # Hence we put those in a separate folder and only move "regular" crates into the vendor folder.
        self.git_vendor_dir = os.path.join(self.builddir, 'easybuild_vendor_git')
        mkdir(self.git_vendor_dir)

        vendor_crates = {self.crate_src_filename(*crate): crate for crate in self.crates}
        # Track git sources for building the cargo config and avoiding duplicated folders
        git_sources = {}

        for src in self.src:
            # Check for git crates, `git_key` will be set to a true-ish value for those
            try:
                crate = vendor_crates[src['name']]
                if len(crate) == 5:
                    crate_name, _, git_repo, rev, branch = crate
                else:
                    crate_name, _, git_repo, rev = crate
                    branch = self.BRANCH_MISSING
            except (ValueError, KeyError):
                git_key = None
            else:
                git_key = (git_repo, rev, branch)
                self.log.debug("Sources of %s(%s) belong to git repo: %s rev %s",
                               crate_name, src['name'], git_repo, rev)
                # Do a sanity check that sources for the same repo and revision are the same
                try:
                    previous_source = git_sources[git_key]
                except KeyError:
                    git_sources[git_key] = src
                else:
                    previous_checksum = get_checksum(previous_source, self.log)
                    current_checksum = get_checksum(src, self.log)
                    if previous_checksum and current_checksum and previous_checksum != current_checksum:
                        raise EasyBuildError("Sources for the same git repository need to be identical. "
                                             "Mismatch found for %s rev %s in %s (checksum: %s) vs %s (checksum: %s)",
                                             git_repo, rev, previous_source['name'], previous_checksum,
                                             src['name'], current_checksum)
                    self.log.info("Source %s already extracted to %s by %s. Skipping extraction.",
                                  src['name'], previous_source['finalpath'], previous_source['name'])
                    src['finalpath'] = previous_source['finalpath']
                    continue

            # Check if the source is a vendored crate and store the crate name
            try:
                crate_name = vendor_crates[src['name']][0]
            except KeyError:
                is_vendor_crate = False
            else:
                is_vendor_crate = True
                src['crate_name'] = crate_name

            # Extract dependency crates into vendor subdirectory, separate from sources of main package
            if is_vendor_crate:
                extraction_dir = self.git_vendor_dir if git_key else self.vendor_dir
            else:
                extraction_dir = self.builddir

            self.log.info("Unpacking source of %s", src['name'])
            existing_dirs = set(os.listdir(extraction_dir))
            src_dir = extract_file(src['path'], extraction_dir, cmd=src['cmd'],
                                   extra_options=self.cfg['unpack_options'], change_into_dir=False)
            new_extracted_dirs = set(os.listdir(extraction_dir)) - existing_dirs

            if len(new_extracted_dirs) == 0:
                # Extraction went wrong
                raise EasyBuildError("Unpacking sources of '%s' failed", src['name'])
            # Expected crate tarball with 1 folder
            # TODO: properly handle case with multiple extracted folders
            # this is currently in a grey area, might still be used by cargo
            if len(new_extracted_dirs) == 1:
                src_dir = os.path.join(extraction_dir, new_extracted_dirs.pop())
                self.log.debug("Unpacked sources of %s into: %s", src['name'], src_dir)

                if is_vendor_crate and self.cfg['offline']:
                    # Create checksum file for extracted sources required by vendored crates

                    # By default there is only a single crate
                    crate_dirs = [src_dir]
                    # For git sources determine the folders that contain crates by taking workspaces into account
                    if git_key:
                        member_dirs = get_workspace_members(src_dir)
                        if member_dirs:
                            crate_dirs = member_dirs

                    try:
                        checksum = src[CHECKSUM_TYPE_SHA256]
                    except KeyError:
                        checksum = compute_checksum(src['path'], checksum_type=CHECKSUM_TYPE_SHA256)
                    for crate_dir in crate_dirs:
                        self.log.info('creating .cargo-checksums.json file for %s', os.path.basename(crate_dir))
                        chkfile = os.path.join(src_dir, crate_dir, '.cargo-checksum.json')
                        write_file(chkfile, CARGO_CHECKSUM_JSON.format(checksum=checksum))
                    # Move non-workspace git crates to the vendor folder
                    if git_key and member_dirs is None:
                        src_dir = os.path.join(self.vendor_dir, os.path.basename(crate_dirs[0]))
                        self.log.debug('Moving crate %s without workspaces to vendor folder', crate_name)
                        move_file(crate_dirs[0], src_dir)

            src['finalpath'] = src_dir

        if self.cfg['offline']:
            self._setup_offline_config(git_sources)

    def _setup_offline_config(self, git_sources):
        """Setup the configuration required for offline builds

        :param git_sources: dict mapping (git_repo, rev) to extracted source
                            rev is a tuple of (revision, branch) or just the revision for older easyconfigs
        """
        self.log.info("Setting up vendored crates for offline operation")
        self.log.debug("Writting config.toml entry for vendored crates from crate.io")
        config_toml = os.path.join(self.cargo_home, 'config.toml')
        # Replace crates-io with vendored sources using build dir wide toml file in CARGO_HOME
        write_file(config_toml, CONFIG_TOML_SOURCE_VENDOR.format(vendor_dir=self.vendor_dir))

        # Tell cargo about the vendored git sources to avoid it failing with:
        # Unable to update https://github.com/[...]
        # can't checkout from 'https://github.com/[...]]': you are in the offline mode (--offline)

        # Unique revisions per repo
        repo_revs = defaultdict(set)
        for src, rev, _ in git_sources:
            repo_revs[src].add(rev)
        for (git_repo, rev, branch), src in git_sources.items():
            src_dir = src['finalpath']
            if os.path.dirname(src_dir) == self.vendor_dir:
                # Non-workspace sources are in vendor_dir
                # We want to specify the repo using the revision and optional branch used which is most reliable.
                if branch is not self.BRANCH_MISSING or len(repo_revs[git_repo]) > 1:
                    self.log.debug("Writing config.toml entry for git repo: %s branch %s, rev %s",
                                   git_repo, branch, rev)
                    branch_info = 'branch = "%s"\n' % branch if branch else '\n'
                    write_file(config_toml,
                               CONFIG_TOML_SOURCE_GIT.format(url=git_repo, rev=rev) + branch_info,
                               append=True)
            else:
                self.log.debug("Writing config.toml entry for git repo: %s rev %s", git_repo, rev)
                # Workspace sources stay in their own separate folder.
                # We cannot have a `directory = "<dir>"` entry where a folder containing a workspace is inside
                write_file(config_toml,
                           CONFIG_TOML_SOURCE_GIT_WORKSPACE.format(url=git_repo, rev=rev, workspace_dir=src_dir),
                           append=True)

        # Use environment variable since it would also be passed along to builds triggered via python packages
        env.setvar('CARGO_NET_OFFLINE', 'true')

    def configure_step(self):
        """Empty configuration step."""
        pass

    @property
    def profile(self):
        return 'debug' if self.toolchain.options.get('debug', None) else 'release'

    def build_step(self):
        """Build with cargo"""
        parallel = ''
        if self.cfg['parallel']:
            parallel = "-j %s" % self.cfg['parallel']

        tests = ''
        if self.cfg['enable_tests']:
            tests = "--tests"

        lto = ''
        if self.cfg['lto'] is not None:
            lto = '--config profile.%s.lto=\\"%s\\"' % (self.profile, self.cfg['lto'])

        run_cmd('rustc --print cfg', log_all=True, simple=True)  # for tracking in log file
        cmd = ' '.join([
            self.cfg['prebuildopts'],
            'cargo build',
            '--profile=' + self.profile,
            lto,
            tests,
            parallel,
            self.cfg['buildopts'],
        ])
        run_cmd(cmd, log_all=True, simple=True)

    def test_step(self):
        """Test with cargo"""
        if self.cfg['enable_tests']:
            cmd = ' '.join([
                self.cfg['pretestopts'],
                'cargo test',
                '--profile=' + self.profile,
                self.cfg['testopts'],
            ])
            run_cmd(cmd, log_all=True, simple=True)

    def install_step(self):
        """Install with cargo"""
        cmd = ' '.join([
            self.cfg['preinstallopts'],
            'cargo install',
            '--profile=' + self.profile,
            '--root=' + self.installdir,
            '--path=.',
            self.cfg['installopts'],
        ])
        run_cmd(cmd, log_all=True, simple=True)


def generate_crate_list(sourcedir):
    """Helper for generating crate list"""
    import toml  # pylint: disable=import-outside-toplevel
    from urllib.parse import parse_qs, urlsplit  # pylint: disable=import-outside-toplevel

    cargo_toml = toml.load(os.path.join(sourcedir, 'Cargo.toml'))

    try:
        cargo_lock = toml.load(os.path.join(sourcedir, 'Cargo.lock'))
    except FileNotFoundError as err:
        print("\nNo Cargo.lock file found. Generate one with 'cargo generate-lockfile'\n")
        raise err

    try:
        app_name = cargo_toml['package']['name']
    except KeyError:
        app_name = os.path.basename(os.path.abspath(sourcedir))
        print_warning('Did not find a [package] name= entry. Assuming it is the folder name: ' + app_name)

    app_in_cratesio = False
    crates = []
    other_crates = []
    for dep in cargo_lock['package']:
        name = dep['name']
        version = dep['version']
        try:
            source_url = dep['source']
        except KeyError:
            other_crates.append((name, version))
            continue
        if name == app_name:
            app_in_cratesio = True  # exclude app itself, needs to be first in crates list or taken from pypi
        else:
            if source_url == 'registry+https://github.com/rust-lang/crates.io-index':
                crates.append((name, version))
            else:
                # Lock file has revision and branch in the url
                url = re.sub(r'^(registry|git)\+', '', source_url)  # Strip prefix if present
                parsed_url = urlsplit(url)
                url = re.split('[#?]', url, maxsplit=1)[0]  # Remove query and fragment
                rev = parsed_url.fragment
                if not rev:
                    raise ValueError("Revision not found in URL %s" % url)
                qs = parse_qs(parsed_url.query)
                rev_qs, branch = qs.get('rev'), qs.get('branch', [None])[0]
                if rev_qs is not None and rev_qs != rev:
                    raise ValueError("Found different revision in query of URL "
                                     "%s: %s, expected: %s" % (url, rev_qs, rev))
                crates.append((name, version, url, rev, branch))
    return app_in_cratesio, crates, other_crates


def main():
    import sys  # pylint: disable=import-outside-toplevel
    if len(sys.argv) != 2:
        print('Expected path to folder containing Cargo.[toml,lock]')
        sys.exit(1)
    app_in_cratesio, crates, other = generate_crate_list(sys.argv[1])
    print('Other crates (no source in Cargo.lock):', other)
    if app_in_cratesio or crates:
        print('crates = [')
        if app_in_cratesio:
            print('    (name, version),')
        for crate_info in sorted(crates):
            print("    %s," % str(crate_info))
        print(']')


if __name__ == '__main__':
    main()
