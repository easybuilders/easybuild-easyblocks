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
import shutil
import tempfile
from glob import glob

import easybuild.tools.environment as env
import easybuild.tools.systemtools as systemtools
from easybuild.framework.easyconfig import CUSTOM
from easybuild.framework.extensioneasyblock import ExtensionEasyBlock
from easybuild.tools.build_log import EasyBuildError, print_warning
from easybuild.tools.config import build_option
from easybuild.tools.filetools import CHECKSUM_TYPE_SHA256, compute_checksum, copy_dir, extract_file, mkdir
from easybuild.tools.filetools import read_file, remove_dir, write_file
from easybuild.tools.run import run_shell_cmd
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

CONFIG_TOML_SOURCE_GIT_BRANCH = """
[source."{url}?rev={rev}"]
git = "{url}"
rev = "{rev}"
branch = "{branch}"
replace-with = "vendored-sources"
"""

CARGO_CHECKSUM_JSON = '{{"files": {{}}, "package": "{checksum}"}}'


def get_virtual_workspace_members(crate_dir):
    """Find all members of a cargo virtual workspace in crate_dir.

    (Minimally) parse the Cargo.toml file.
    If it is a virtual workspace ([workspace] and no [package]) return all members (subfolder names).
    Otherwise return None.
    """
    cargo_toml = os.path.join(crate_dir, 'Cargo.toml')
    lines = [line.strip() for line in read_file(cargo_toml).splitlines()]
    if '[package]' in lines:
        return None

    # We are looking for this:
    # [workspace]
    # members = [
    # "reqwest-middleware",
    # "reqwest-tracing",
    # "reqwest-retry",
    # ]

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
    return members


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

    @staticmethod
    def extra_options(extra_vars=None):
        """Define extra easyconfig parameters specific to Cargo"""
        extra_vars = ExtensionEasyBlock.extra_options(extra_vars)
        extra_vars.update({
            'enable_tests': [True, "Enable building of tests", CUSTOM],
            'offline': [True, "Build offline", CUSTOM],
            'lto': [None, "Override default LTO flag ('fat', 'thin', 'off')", CUSTOM],
            'crates': [[], "List of (crate, version, [repo, rev]) tuples to use", CUSTOM],
        })

        return extra_vars

    @staticmethod
    def crate_src_filename(pkg_name, pkg_version, _url=None, rev=None):
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
        return f"{pkg_name}/{pkg_version}/download"

    def rustc_optarch(self):
        """Determines what architecture to target.
        Translates GENERIC optarch, and respects rustc specific optarch.
        General optarchs are ignored as there is no direct translation.
        """
        generic = '-C target-cpu=generic'
        if systemtools.get_cpu_architecture() == systemtools.X86_64:
            generic = '-C target-cpu=x86-64'

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
                self.log.info(f"Given 'optarch' has no specific information on rustc, so using {optimal}")
            elif optarch == OPTARCH_GENERIC:
                return generic
            else:
                self.log.warning(f"Ignoring 'optarch' because there is no translation for rustc, so using {optimal}")

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
                crate, version, repo, rev = crate_info
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

        vendor_crates = {self.crate_src_filename(*crate): crate for crate in self.crates}
        # Track git sources for building the cargo config and avoiding duplicated folders
        git_sources = {}

        for src in self.src:
            # Check if the source is a vendored crate
            is_vendor_crate = src['name'] in vendor_crates
            if is_vendor_crate:
                # Store crate for later
                src['crate'] = vendor_crates[src['name']]
                crate_name = src['crate'][0]

            # Check for git crates, `git_key` will be set to a true-ish value for those
            if not is_vendor_crate or len(src['crate']) == 2:
                git_key = None
            else:
                git_key = src['crate'][2:]
                git_repo, rev = git_key
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

            # Extract dependency crates into vendor subdirectory, separate from sources of main package
            extraction_dir = self.vendor_dir if is_vendor_crate else self.builddir

            self.log.info("Unpacking source of %s", src['name'])
            existing_dirs = set(os.listdir(extraction_dir))
            extract_file(src['path'], extraction_dir, cmd=src['cmd'],
                         extra_options=self.cfg['unpack_options'], change_into_dir=False)
            new_extracted_dirs = set(os.listdir(extraction_dir)) - existing_dirs

            if len(new_extracted_dirs) == 0:
                # Extraction went wrong
                raise EasyBuildError("Unpacking sources of '%s' failed", src['name'])
            # There can be multiple folders but we just use the first new one as the finalpath
            if len(new_extracted_dirs) > 1:
                self.log.warning(f"Found multiple folders when extracting {src['name']}: "
                                 f"{', '.join(new_extracted_dirs)}.")
            src_dir = os.path.join(extraction_dir, new_extracted_dirs.pop())
            self.log.debug("Unpacked sources of %s into: %s", src['name'], src_dir)

            src['finalpath'] = src_dir

        if self.cfg['offline']:
            self._setup_offline_config(git_sources)

    def _setup_offline_config(self, git_sources):
        """
        Setup the configuration required for offline builds
        :param git_sources: dict mapping (git_repo, rev) to extracted source
        """
        self.log.info("Setting up vendored crates for offline operation")

        self.log.debug("Setting up checksum files and unpacking workspaces with virtual manifest")
        path_to_source = {src['finalpath']: src for src in self.src}
        tmp_dir = tempfile.mkdtemp(dir=self.builddir, prefix='tmp_crate_')
        # Add checksum file for each crate such that it is recognized by cargo.
        # Glob to catch multiple folders in a source archive.
        crate_dirs = [os.path.dirname(p) for p in glob(os.path.join(self.vendor_dir, '*', 'Cargo.toml'))]
        for crate_dir in crate_dirs:
            src = path_to_source.get(crate_dir)
            if src:
                try:
                    checksum = src[CHECKSUM_TYPE_SHA256]
                except KeyError:
                    self.log.debug(f"Computing checksum for {src['path']}.")
                    checksum = compute_checksum(src['path'], checksum_type=CHECKSUM_TYPE_SHA256)
            else:
                self.log.debug(f'No source found for {crate_dir}. Using nul-checksum for vendoring')
                checksum = 'null'
            # Sources might contain multiple crates/folders in a so-called "workspace".
            # If there isn't a main package (Only "[workspace]" section and no "[package]" section) we have to move
            # the individual packages out of the workspace or cargo fails with
            # "found a virtual manifest at [...]Cargo.toml instead of a package manifest"
            member_dirs = get_virtual_workspace_members(crate_dir)
            if member_dirs:
                self.log.info(f'Found virtual manifest in {crate_dir}. Members: ' + ', '.join(member_dirs))
                crate_dirs = []
                tmp_crate_dir = os.path.join(tmp_dir, os.path.basename(crate_dir))
                shutil.move(crate_dir, tmp_crate_dir)
                for crate in member_dirs:
                    target_path = os.path.join(self.vendor_dir, crate)
                    if os.path.exists(target_path):
                        raise EasyBuildError(f'Cannot move {crate} out of {os.path.basename(crate_dir)} '
                                             f'as target path {target_path} exists')
                    # Use copy_dir to resolve symlinks that might point to the parent folder
                    copy_dir(os.path.join(tmp_crate_dir, crate), target_path, symlinks=False)
                    crate_dirs.append(target_path)
                remove_dir(tmp_crate_dir)
            else:
                crate_dirs = [crate_dir]
            for crate_dir in crate_dirs:
                self.log.info('creating .cargo-checksums.json file for %s', os.path.basename(crate_dir))
                chkfile = os.path.join(crate_dir, '.cargo-checksum.json')
                write_file(chkfile, CARGO_CHECKSUM_JSON.format(checksum=checksum))

        self.log.debug("Writting config.toml entry for vendored crates from crate.io")
        config_toml = os.path.join(self.cargo_home, 'config.toml')
        # Replace crates-io with vendored sources using build dir wide toml file in CARGO_HOME
        write_file(config_toml, CONFIG_TOML_SOURCE_VENDOR.format(vendor_dir=self.vendor_dir))

        # Tell cargo about the vendored git sources to avoid it failing with:
        # Unable to update https://github.com/[...]
        # can't checkout from 'https://github.com/[...]]': you are in the offline mode (--offline)
        for (git_repo, rev), src in git_sources.items():
            crate_name = src['crate'][0]
            git_branch = self._get_crate_git_repo_branch(crate_name)
            template = CONFIG_TOML_SOURCE_GIT_BRANCH if git_branch else CONFIG_TOML_SOURCE_GIT
            self.log.debug(f"Writing config.toml entry for git repo: {git_repo} branch {git_branch}, rev {rev}")
            write_file(config_toml, template.format(url=git_repo, rev=rev, branch=git_branch), append=True)

        # Use environment variable since it would also be passed along to builds triggered via python packages
        env.setvar('CARGO_NET_OFFLINE', 'true')

    def _get_crate_git_repo_branch(self, crate_name):
        """
        Find the dependency definition for given crate in all Cargo.toml files of sources
        Return branch target for given crate_name if any
        """
        # Search all Cargo.toml files in main source and vendored crates
        cargo_toml_files = []
        for cargo_source_dir in (self.src[0]['finalpath'], self.vendor_dir):
            cargo_toml_files.extend(glob(os.path.join(cargo_source_dir, '**', 'Cargo.toml'), recursive=True))

        if not cargo_toml_files:
            raise EasyBuildError("Cargo.toml file not found in sources")

        self.log.debug(
            f"Searching definition of crate '{crate_name}' in the following files: {', '.join(cargo_toml_files)}"
        )

        git_repo_spec = re.compile(re.escape(crate_name) + r"\s*=\s*{([^}]*)}", re.M)
        git_branch_spec = re.compile(r'branch\s*=\s*"([^"]*)"', re.M)

        for cargo_toml in cargo_toml_files:
            git_repo_crate = git_repo_spec.search(read_file(cargo_toml))
            if git_repo_crate:
                self.log.debug(f"Found specification in {cargo_toml} for crate '{crate_name}': " +
                               git_repo_crate.group())
                git_repo_crate_contents = git_repo_crate.group(1)
                git_branch_crate = git_branch_spec.search(git_repo_crate_contents)
                if git_branch_crate:
                    self.log.debug(f"Found git branch requirement for crate '{crate_name}': " +
                                   git_branch_crate.group())
                    return git_branch_crate.group(1)

        return None

    def configure_step(self):
        """Empty configuration step."""
        pass

    @property
    def profile(self):
        return 'debug' if self.toolchain.options.get('debug', None) else 'release'

    def build_step(self):
        """Build with cargo"""
        parallel = ''
        if self.cfg.parallel > 1:
            parallel = f"-j {self.cfg.parallel}"

        tests = ''
        if self.cfg['enable_tests']:
            tests = "--tests"

        lto = ''
        if self.cfg['lto'] is not None:
            lto = f'--config profile.{self.profile}.lto="{self.cfg["lto"]}"'

        run_shell_cmd('rustc --print cfg')  # for tracking in log file
        cmd = ' '.join([
            self.cfg['prebuildopts'],
            'cargo build',
            '--profile=' + self.profile,
            lto,
            tests,
            parallel,
            self.cfg['buildopts'],
        ])
        run_shell_cmd(cmd)

    def test_step(self):
        """Test with cargo"""
        if self.cfg['enable_tests']:
            cmd = ' '.join([
                self.cfg['pretestopts'],
                'cargo test',
                '--profile=' + self.profile,
                self.cfg['testopts'],
            ])
            run_shell_cmd(cmd)

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
        run_shell_cmd(cmd)


def generate_crate_list(sourcedir):
    """Helper for generating crate list"""
    from urllib.parse import parse_qs, urlsplit  # pylint: disable=import-outside-toplevel

    import toml  # pylint: disable=import-outside-toplevel

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
                    raise ValueError(f"Revision not found in URL {url}")
                qs = parse_qs(parsed_url.query)
                rev_qs = qs.get('rev', [None])[0]
                if rev_qs is not None and rev_qs != rev:
                    raise ValueError(f"Found different revision in query of URL {url}: {rev_qs} (expected: {rev})")
                crates.append((name, version, url, rev))
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
