# Volatility
# Copyright (c) 2008 Volatile Systems
# Copyright (c) 2008 Brendan Dolan-Gavitt <bdolangavitt@wesleyan.edu>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or (at
# your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details. 
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA 02111-1307 USA 
#

import datetime
import socket, struct
import volatility.plugins.kpcrscan as kpcr
import volatility.plugins.kdbgscan as kdbg
import volatility.timefmt as timefmt
import volatility.debug as debug
import volatility.obj as obj
import volatility.addrspace as addrspace


# Standard vtypes are usually autogenerated by scanning through header
# files, collecting debugging symbol data etc. This file defines
# fixups and improvements to the standard types.
windows_overlay = {
    'VOLATILITY_MAGIC' : [None, {
    # Profile specific values
    'DTBSignature' : [ 0x0, ['VolatilityMagic', dict(value = "Volatility DTBSignature unspecified")]],
    'KUSER_SHARED_DATA' : [ 0x0, ['VolatilityMagic', dict(value = 0xFFDF0000)]],
    'KDBGHeader' : [ 0x0, ['VolatilityMagic', dict(value = 'Volatility KDBGHeader unspecified')]],
    # Configuration options
    'DTB' : [ 0x0, ['VolatilityDTB', dict(configname = "DTB")]],
    'KPCR' : [ 0x0, ['VolatilityMagic', dict(value = 0xffdff000, configname = "KPCR")]],
    'KDBG' : [ 0x0, ['VolatilityKDBG', dict(configname = "KDBG")]],
    'IA32ValidAS': [ 0x0, ['VolatilityIA32ValidAS']],
    # Pool allocations are aligned to this many bytes.
    'PoolAlignment': [0x0, ['VolatilityMagic', dict(value = 8)]],
    }],

    '_EPROCESS' : [ None, {
    'CreateTime' : [ None, ['WinTimeStamp', {}]],
    'ExitTime' : [ None, ['WinTimeStamp', {}]],
    'InheritedFromUniqueProcessId' : [ None, ['unsigned int']],
    'ImageFileName' : [ None, ['String', dict(length = 16)]],
    'UniqueProcessId' : [ None, ['unsigned int']],
    }],

    '_ETHREAD' : [ None, {
    'CreateTime' : [ None, ['ThreadCreateTimeStamp', {}]],
    'ExitTime' : [ None, ['WinTimeStamp', {}]],
    }],

    '_OBJECT_SYMBOLIC_LINK' : [ None, {
    'CreationTime' : [ None, ['WinTimeStamp', {}]],
    }],

    '_KUSER_SHARED_DATA' : [ None, {
    'SystemTime' : [ None, ['WinTimeStamp', dict(is_utc = True)]],
    'TimeZoneBias' : [ None, ['WinTimeStamp', {}]],
    }],

    # The DTB is really an array of 2 ULONG_PTR but we only need the first one 
    # which is the value loaded into CR3. The second one, according to procobj.c 
    # of the wrk-v1.2, contains the PTE that maps something called hyper space. 
    '_KPROCESS' : [ None, {
    'DirectoryTableBase' : [ None, ['unsigned long']],
    }],

    '_HANDLE_TABLE_ENTRY' : [ None, {
    'Object' : [ None, ['_EX_FAST_REF']],
    }],

    '_IMAGE_SECTION_HEADER' : [ None, {
    'Name' : [ 0x0, ['String', dict(length = 8)]],
    }],

    '_DBGKD_GET_VERSION64' : [  None, {
    'DebuggerDataList' : [ None, ['pointer', ['unsigned long']]],
    }],

    '_CM_KEY_NODE' : [ None, {
    'Signature' : [ None, ['String', dict(length = 2)]],
    'LastWriteTime' : [ None, ['WinTimeStamp', {}]],
    'Name' : [ None, ['String', dict(length = lambda x: x.NameLength)]],
    }],

    '_CM_NAME_CONTROL_BLOCK' : [ None, {
    'Name' : [ None, ['String', dict(length = lambda x: x.NameLength)]],
    }],

    '_CHILD_LIST' : [ None, {
    'List' : [ None, ['pointer', ['array', lambda x: x.Count,
                                 ['pointer', ['_CM_KEY_VALUE']]]]],
    }],

    '_CM_KEY_VALUE' : [ None, {
    'Signature' : [ None, ['String', dict(length = 2)]],
    'Name' : [ None, ['String', dict(length = lambda x: x.NameLength)]],
    }],

    '_CM_KEY_INDEX' : [ None, {
    'Signature' : [ None, ['String', dict(length = 2)]],
    'List' : [ None, ['array', lambda x: x.Count.v() * 2, ['pointer', ['_CM_KEY_NODE']]]],
    }],

    '_IMAGE_HIBER_HEADER' : [ None, {
    'Signature':   [ None, ['String', dict(length = 4)]],
    'SystemTime' : [ None, ['WinTimeStamp', {}]],
    }],

    '_PHYSICAL_MEMORY_DESCRIPTOR' : [ None, {
    'Run' : [ None, ['array', lambda x: x.NumberOfRuns, ['_PHYSICAL_MEMORY_RUN']]],
    }],

    '_TOKEN' : [ None, {
    'UserAndGroups' : [ None, ['pointer', ['array', lambda x: x.UserAndGroupCount,
                                 ['_SID_AND_ATTRIBUTES']]]],
    }],

    '_SID' : [ None, {
    'SubAuthority' : [ None, ['array', lambda x: x.SubAuthorityCount, ['unsigned long']]],
    }],

    '_CLIENT_ID': [ None, {
    'UniqueProcess' : [ None, ['unsigned int']],
    'UniqueThread' : [ None, ['unsigned int']],
    }],

    '_MMVAD_SHORT': [ None, {
    # This is the location of the MMVAD type which controls how to parse the
    # node. It is located before the structure.
    'Tag': [-4 , ['String', dict(length = 4)]],
    }],

    '_MMVAD_LONG': [ None, {
    # This is the location of the MMVAD type which controls how to parse the
    # node. It is located before the structure.
    'Tag': [-4 , ['String', dict(length = 4)]],
    }],
}

class _UNICODE_STRING(obj.CType):
    """Class representing a _UNICODE_STRING

    Adds the following behavior:
      * The Buffer attribute is presented as a Python string rather
        than a pointer to an unsigned short.
      * The __str__ method returns the value of the Buffer.
    """
    def v(self):
        """
        If the claimed length of the string is acceptable, return a unicode string.
        Otherwise, return a NoneObject.
        """
        data = self.dereference()
        if data:
            return unicode(data)
        return data

    def dereference(self):
        length = self.Length.v()
        if length > 0 and length <= 1024:
            data = self.Buffer.dereference_as('String', encoding = 'utf16', length = length)
            return data
        else:
            return obj.NoneObject("Buffer length {0} for _UNICODE_STRING not within bounds".format(length))

    def proxied(self, _name):
        return str(self)

    def __nonzero__(self):
        ## Unicode strings are valid if they point at a valid memory
        return bool(self.Buffer and self.Length.v() > 0 and self.Length.v() <= 1024)

    def __format__(self, formatspec):
        return format(self.v(), formatspec)

    def __str__(self):
        return str(self.dereference())

    def __unicode__(self):
        return unicode(self.dereference())

class _LIST_ENTRY(obj.CType):
    """ Adds iterators for _LIST_ENTRY types """
    def list_of_type(self, type, member, forward = True):
        if not self.is_valid():
            return

        ## Get the first element
        if forward:
            lst = self.Flink.dereference()
        else:
            lst = self.Blink.dereference()

        offset = self.obj_vm.profile.get_obj_offset(type, member)

        seen = set()
        seen.add(lst.obj_offset)

        while 1:
            ## Instantiate the object
            item = obj.Object(type, offset = lst.obj_offset - offset,
                                    vm = self.obj_vm,
                                    parent = self.obj_parent,
                                    native_vm = self.obj_native_vm,
                                    name = type)


            if forward:
                lst = item.m(member).Flink.dereference()
            else:
                lst = item.m(member).Blink.dereference()

            if not lst.is_valid() or lst.obj_offset in seen:
                return
            seen.add(lst.obj_offset)

            yield item

    def __nonzero__(self):
        ## List entries are valid when both Flinks and Blink are valid
        return bool(self.Flink) or bool(self.Blink)

    def __iter__(self):
        return self.list_of_type(self.obj_parent.obj_name, self.obj_name)

class WinTimeStamp(obj.NativeType):
    """Class for handling Windows Time Stamps"""

    def __init__(self, theType, offset, vm, is_utc = False, **kwargs):
        self.is_utc = is_utc
        obj.NativeType.__init__(self, theType, offset, vm, format_string = "q", **kwargs)

    def windows_to_unix_time(self, windows_time):
        """
        Converts Windows 64-bit time to UNIX time

        @type  windows_time:  Integer
        @param windows_time:  Windows time to convert (64-bit number)

        @rtype  Integer
        @return  UNIX time
        """
        if(windows_time == 0):
            unix_time = 0
        else:
            unix_time = windows_time / 10000000
            unix_time = unix_time - 11644473600

        if unix_time < 0:
            unix_time = 0

        return unix_time

    def as_windows_timestamp(self):
        return obj.NativeType.v(self)

    def v(self):
        value = self.as_windows_timestamp()
        return self.windows_to_unix_time(value)

    def __nonzero__(self):
        return self.v() != 0

    def __str__(self):
        return "{0}".format(self)

    def as_datetime(self):
        try:
            dt = datetime.datetime.utcfromtimestamp(self.v())
            if self.is_utc:
                # Only do dt.replace when dealing with UTC
                dt = dt.replace(tzinfo = timefmt.UTC())
        except ValueError, e:
            return obj.NoneObject("Datetime conversion failure: " + str(e))
        return dt

    def __format__(self, formatspec):
        """Formats the datetime according to the timefmt module"""
        dt = self.as_datetime()
        if dt != None:
            return format(timefmt.display_datetime(dt), formatspec)
        return "-"

class _EPROCESS(obj.CType):
    """ An extensive _EPROCESS with bells and whistles """
    @property
    def Peb(self):
        """ Returns a _PEB object which is using the process address space.

        The PEB structure is referencing back into the process address
        space so we need to switch address spaces when we look at
        it. This method ensure this happens automatically.
        """
        process_ad = self.get_process_address_space()
        if process_ad:
            offset = self.m("Peb").v()
            peb = obj.Object("_PEB", offset, vm = process_ad,
                                    name = "Peb", parent = self)

            if peb.is_valid():
                return peb

        return obj.NoneObject("Peb not found")

    def get_process_address_space(self):
        """ Gets a process address space for a task given in _EPROCESS """
        directory_table_base = self.Pcb.DirectoryTableBase.v()

        try:
            process_as = self.obj_vm.__class__(self.obj_vm.base, self.obj_vm.get_config(), dtb = directory_table_base)
        except AssertionError, _e:
            return obj.NoneObject("Unable to get process AS")

        process_as.name = "Process {0}".format(self.UniqueProcessId)

        return process_as

    def _get_modules(self, the_list, the_type):
        """Generator for DLLs in one of the 3 PEB lists"""
        if self.UniqueProcessId and the_list:
            for l in the_list.list_of_type("_LDR_DATA_TABLE_ENTRY", the_type):
                yield l

    def get_init_modules(self):
        return self._get_modules(self.Peb.Ldr.InInitializationOrderModuleList, "InInitializationOrderLinks")

    def get_mem_modules(self):
        return self._get_modules(self.Peb.Ldr.InMemoryOrderModuleList, "InMemoryOrderLinks")

    def get_load_modules(self):
        return self._get_modules(self.Peb.Ldr.InLoadOrderModuleList, "InLoadOrderLinks")

    def get_vads(self):
        """Generator for MMVADs that does not rely on named AS"""
        procspace = self.get_process_address_space()

        # Potentially get_process_address_space will return obj.NoneObject
        if procspace:
            vadroot = obj.Object('_MMVAD', offset = self.VadRoot, vm = procspace)

            if vadroot:
                for v in vadroot.traverse():
                    yield v

    def get_token(self):
        """Return the process's TOKEN object if its valid"""

        # The dereference checks if the address is valid  
        # and returns obj.NoneObject if it fails 
        token = self.Token.dereference_as("_TOKEN")

        # This check fails if the above dereference failed 
        # or if any of the _TOKEN specific validity tests failed. 
        if token.is_valid():
            return token

        return obj.NoneObject("Cannot get process Token")

class _TOKEN(obj.CType):
    """A class for Tokens"""

    def is_valid(self):
        """Override BaseObject.is_valid with some additional
        checks specific to _TOKEN objects."""
        return obj.CType.is_valid(self) and self.TokenInUse in (0, 1) and self.SessionId < 10

    def get_sids(self):
        """Generator for process SID strings"""
        if self.UserAndGroupCount < 0xFFFF:
            for sa in self.UserAndGroups.dereference():
                sid = sa.Sid.dereference_as('_SID')
                for i in sid.IdentifierAuthority.Value:
                    id_auth = i
                yield "S-" + "-".join(str(i) for i in (sid.Revision, id_auth) +
                                      tuple(sid.SubAuthority))

class _ETHREAD(obj.CType):
    """ A class for threads """

    def owning_process(self):
        """Return the EPROCESS that owns this thread"""
        return self.ThreadsProcess.dereference()

    def attached_process(self):
        """Return the EPROCESS that this thread is currently
        attached to."""
        return self.Tcb.ApcState.Process.dereference_as("_EPROCESS")

class _HANDLE_TABLE(obj.CType):
    """ A class for _HANDLE_TABLE. 
    
    This used to be a member of _EPROCESS but it was isolated per issue 
    91 so that it could be subclassed and used to service other handle 
    tables, such as the _KDDEBUGGER_DATA64.PspCidTable.
    """

    def get_item(self, entry, handle_value = 0):
        """Returns the OBJECT_HEADER of the associated handle. The parent
        is the _HANDLE_TABLE_ENTRY so that an object can be linked to its 
        GrantedAccess.
        """
        return entry.Object.dereference_as("_OBJECT_HEADER", parent = entry, handle_value = handle_value)

    def _make_handle_array(self, offset, level, depth = 0):
        """ Returns an array of _HANDLE_TABLE_ENTRY rooted at offset,
        and iterates over them.
        """

        # The counts below are calculated by taking the size of a page and dividing 
        # by the size of the data type contained within the page. For more information
        # see http://blogs.technet.com/b/markrussinovich/archive/2009/09/29/3283844.aspx
        if level > 0:
            count = 0x1000 / self.obj_vm.profile.get_obj_size("address")
            targetType = "address"
        else:
            count = 0x1000 / self.obj_vm.profile.get_obj_size("_HANDLE_TABLE_ENTRY")
            targetType = "_HANDLE_TABLE_ENTRY"

        table = obj.Object("Array", offset = offset, vm = self.obj_vm, count = count,
                           targetType = targetType, parent = self, native_vm = self.obj_native_vm)

        if table:
            for entry in table:
                if not entry.is_valid():
                    break

                if level > 0:
                    ## We need to go deeper:
                    for h in self._make_handle_array(entry, level - 1, depth):
                        yield h
                    depth += 1
                else:

                    # All handle values are multiples of four, on both x86 and x64. 
                    handle_multiplier = 4
                    # Calculate the starting handle value for this level. 
                    handle_level_base = depth * count * handle_multiplier
                    # The size of a handle table entry.
                    handle_entry_size = self.obj_vm.profile.get_obj_size("_HANDLE_TABLE_ENTRY")
                    # Finally, compute the handle value for this object. 
                    handle_value = ((entry.obj_offset - offset) /
                                   (handle_entry_size / handle_multiplier)) + handle_level_base

                    ## OK We got to the bottom table, we just resolve
                    ## objects here:
                    item = self.get_item(entry, handle_value)

                    if item == None:
                        continue

                    try:
                        # New object header
                        if item.TypeIndex != 0x0:
                            yield item
                    except AttributeError:
                        if item.Type.Name:
                            yield item

    def handles(self):
        """ A generator which yields this process's handles

        _HANDLE_TABLE tables are multi-level tables at the first level
        they are pointers to second level table, which might be
        pointers to third level tables etc, until the final table
        contains the real _OBJECT_HEADER table.

        This generator iterates over all the handles recursively
        yielding all handles. We take care of recursing into the
        nested tables automatically.
        """
        # This should work equally for 32 and 64 bit systems
        LEVEL_MASK = 7

        TableCode = self.TableCode.v() & ~LEVEL_MASK
        table_levels = self.TableCode.v() & LEVEL_MASK
        offset = TableCode

        for h in self._make_handle_array(offset, table_levels):
            yield h

class _OBJECT_HEADER(obj.CType):
    """A Volatility object to handle Windows object headers.

    This object applies only to versions below windows 7.
    """

    optional_headers = [('NameInfo', '_OBJECT_HEADER_NAME_INFO'),
                        ('HandleInfo', '_OBJECT_HEADER_HANDLE_INFO'),
                        ('QuotaInfo', '_OBJECT_HEADER_QUOTA_INFO')]

    def __init__(self, *args, **kwargs):
        # Usually we don't add members to objects like this, but its an
        # exception due to lack of better options. See Issue #135. 
        self.HandleValue = kwargs.get("handle_value", 0)
        obj.CType.__init__(self, *args, **kwargs)
        # Create accessors for optional headers
        self.find_optional_headers()

    def find_optional_headers(self):
        """Find this object's optional headers."""
        offset = self.obj_offset

        for name, objtype in self.optional_headers:
            if self.obj_vm.profile.has_type(objtype):
                header_offset = self.m(name + 'Offset').v()
                if header_offset:
                    o = obj.Object(objtype, offset - header_offset, vm = self.obj_vm, native_vm = self.obj_native_vm)
                else:
                    o = obj.NoneObject("Header not set")

                self.newattr(name, o)

    @property
    def GrantedAccess(self):
        if self.obj_parent:
            return self.obj_parent.GrantedAccess
        return obj.NoneObject("No parent known")

    def dereference_as(self, theType):
        """Instantiate an object from the _OBJECT_HEADER.Body"""
        return obj.Object(theType, offset = self.Body.obj_offset, vm = self.obj_vm,
                         native_vm = self.obj_native_vm, parent = self)

    def get_object_type(self):
        """Return the object's type as a string"""
        type_obj = obj.Object("_OBJECT_TYPE", self.Type, self.obj_native_vm)

        return type_obj.Name.v()

class _FILE_OBJECT(obj.CType):
    """Class for file objects"""

    def file_name_with_device(self):
        """Return the name of the file, prefixed with the name
        of the device object to which the file belongs"""
        name = ""
        if self.DeviceObject:
            object_hdr = obj.Object("_OBJECT_HEADER",
                            self.DeviceObject - self.obj_vm.profile.get_obj_offset("_OBJECT_HEADER", "Body"),
                            self.obj_native_vm)
            if object_hdr:
                name = "\\Device\\{0}".format(str(object_hdr.NameInfo.Name))
        if self.FileName:
            name += str(self.FileName)
        return name

    def access_string(self):
        ## Make a nicely formatted ACL string
        AccessStr = (((self.ReadAccess > 0 and "R") or '-') +
                     ((self.WriteAccess > 0  and "W") or '-') +
                     ((self.DeleteAccess > 0 and "D") or '-') +
                     ((self.SharedRead > 0 and "r") or '-') +
                     ((self.SharedWrite > 0 and "w") or '-') +
                     ((self.SharedDelete > 0 and "d") or '-'))
        return AccessStr

## This is an object which provides access to the VAD tree.
class _MMVAD(obj.CType):
    """Class factory for _MMVAD objects"""

    ## The actual type depends on this tag value.
    tag_map = {'Vadl': '_MMVAD_LONG',
               'VadS': '_MMVAD_SHORT',
               'Vad ': '_MMVAD_LONG',
               'VadF': '_MMVAD_SHORT',
               'Vadm': '_MMVAD_LONG',
              }

    ## parent is the containing _EPROCESS right now
    def __new__(cls, theType, offset, vm, parent = None, **args):
        # Don't waste time if we're based on a NULL pointer
        # I can't think of a better check than this...
        if offset < 4:
            return obj.NoneObject("MMVAD probably instantiated from a NULL pointer, there is no tag to read")

        if not vm:
            return obj.NoneObject("Could not find address space for _MMVAD object")

        ## Note that since we were called from __new__ we can return a
        ## completely different object here (including
        ## NoneObject). This also means that we can not add any
        ## specialist methods to the _MMVAD class.
        if vm.name.startswith('Kernel'):
            debug.warning("Instantiating _MMVAD objects from the wrong address has been deprecated\nPlease use _EPROCESS.get_vads() instead")

        ## We must not polute Object's constructor by providing the
        ## members or struct_size we were instantiated with
        args.pop('struct_size', None)
        args.pop('members', None)

        # Start off with an _MMVAD_LONG
        result = obj.Object('_MMVAD_LONG', offset = offset, vm = vm, parent = parent, **args)

        # Get the tag and change the vad type if necessary
        real_type = cls.tag_map.get(str(result.Tag), None)
        if not real_type:
            return obj.NoneObject("Tag {0} not known".format(str(result.Tag)))

        if result.__class__.__name__ != real_type:
            result = obj.Object(real_type, offset = offset, vm = vm, parent = parent, **args)

        return result

class _MMVAD_SHORT(obj.CType):
    """Class with convenience functions for _MMVAD_SHORT functions"""
    def traverse(self, visited = None):
        """ Traverse the VAD tree by generating all the left items,
        then the right items.

        We try to be tolerant of cycles by storing all offsets visited.
        """
        if visited == None:
            visited = set()

        ## We try to prevent loops here
        if self.obj_offset in visited:
            return

        yield self

        for c in self.LeftChild.traverse(visited = visited):
            visited.add(c.obj_offset)
            yield c

        for c in self.RightChild.traverse(visited = visited):
            visited.add(c.obj_offset)
            yield c

    def get_parent(self):
        """Returns the Parent of the MMVAD"""
        return self.Parent

    def get_control_area(self):
        """Returns the ControlArea of the MMVAD"""
        return self.ControlArea

    def get_file_object(self):
        """Returns the FilePointer of the ControlArea of the MMVAD"""
        return self.ControlArea.FilePointer.dereference()

    def get_start(self):
        """Get the starting virtual address"""
        return self.StartingVpn << 12

    def get_end(self):
        """Get the ending virtual address"""
        return ((self.EndingVpn + 1) << 12) - 1

    def get_data(self):
        """Get the data in a vad region"""

        start = self.get_start()
        end = self.get_end()

        # avoid potential invalid values 
        if start > 0xFFFFFFFF or end > (0xFFFFFFFF << 12):
            return ''

        # obj_vm is process space 
        return self.obj_vm.zread(start, end - start + 1)

class _MMVAD_LONG(_MMVAD_SHORT):
    """Subclasses _MMVAD_LONG based on _MMVAD_SHORT"""
    pass

class _EX_FAST_REF(obj.CType):

    MAX_FAST_REF = 7

    def dereference_as(self, theType, parent = None, **kwargs):
        """Use the _EX_FAST_REF.Object pointer to resolve an object of the specified type"""
        return obj.Object(theType, self.Object.v() & ~self.MAX_FAST_REF, self.obj_native_vm, parent = parent or self, **kwargs)

class ThreadCreateTimeStamp(WinTimeStamp):
    """Handles ThreadCreateTimeStamps which are bit shifted WinTimeStamps"""
    def __init__(self, *args, **kwargs):
        WinTimeStamp.__init__(self, *args, **kwargs)

    def as_windows_timestamp(self):
        return obj.NativeType.v(self) >> 3

class IpAddress(obj.NativeType):
    """Provides proper output for IpAddress objects"""

    def __init__(self, theType, offset, vm, **kwargs):
        obj.NativeType.__init__(self, theType, offset, vm, format_string = vm.profile.native_types['unsigned long'][1], **kwargs)

    def v(self):
        return socket.inet_ntoa(struct.pack("<I", obj.NativeType.v(self)))

class VolatilityKPCR(obj.VolatilityMagic):
    """A scanner for KPCR data within an address space"""

    def __init__(self, *args, **kwargs):
        # Remove the value kwarg since overlaying one 
        # on the other would give the value precedence
        kwargs.pop('value', None)
        obj.VolatilityMagic.__init__(self, *args, **kwargs)

    def generate_suggestions(self):
        """Returns the results of KCPRScanner for an adderss space"""
        scanner = kpcr.KPCRScanner()
        for val in scanner.scan(self.obj_vm):
            yield val

class VolatilityKDBG(obj.VolatilityMagic):
    """A Scanner for KDBG data within an address space"""

    def generate_suggestions(self):
        """Generates a list of possible KDBG structure locations"""
        scanner = kdbg.KDBGScanner(needles = [obj.VolMagic(self.obj_vm).KDBGHeader.v()])
        for val in scanner.scan(self.obj_vm):
            yield val

class VolatilityIA32ValidAS(obj.VolatilityMagic):
    """An object to check that an address space is a valid IA32 Paged space"""

    def generate_suggestions(self):
        """Generates a single response of True or False depending on whether the space is a valid Windows AS"""
        # This constraint looks for self referential values within
        # the paging tables
        try:
            if self.obj_vm.pae:
                pde_base = 0xc0600000
                pd = self.obj_vm.get_pdpte(0) & 0xffffffffff000
            else:
                pde_base = 0xc0300000
                pd = self.obj_vm.dtb
            if (self.obj_vm.vtop(pde_base) == pd):
                yield True
                raise StopIteration

        except addrspace.ASAssertionError, _e:
            pass
        debug.debug("Failed to pass the Moyix Valid IA32 AS test", 3)

        # This constraint verifies that _KUSER_ SHARED_DATA is shared
        # between user and kernel address spaces.
        if (self.obj_vm.vtop(0xffdf0000)) == (self.obj_vm.vtop(0x7ffe0000)):
            if self.obj_vm.vtop(0xffdf0000) != None:
                yield True
                raise StopIteration
        debug.debug("Failed to pass the labarum_x Valid IA32 AS test", 3)

        yield False

class _IMAGE_DOS_HEADER(obj.CType):
    """DOS header"""

    def get_nt_header(self):
        """Get the NT header"""

        if self.e_magic != 0x5a4d:
            raise ValueError('e_magic {0:04X} is not a valid DOS signature.'.format(self.e_magic))

        nt_header = obj.Object("_IMAGE_NT_HEADERS",
                          offset = self.e_lfanew + self.obj_offset,
                          vm = self.obj_vm,
                          native_vm = self.obj_native_vm)

        if nt_header.Signature != 0x4550:
            raise ValueError('NT header signature {0:04X} is not a valid'.format(nt_header.Signature))

        return nt_header

class _IMAGE_NT_HEADERS(obj.CType):
    """PE header"""

    def get_sections(self, unsafe):
        """Get the PE sections"""
        sect_size = self.obj_vm.profile.get_obj_size("_IMAGE_SECTION_HEADER")
        start_addr = self.FileHeader.SizeOfOptionalHeader + self.OptionalHeader.obj_offset

        for i in range(self.FileHeader.NumberOfSections):
            s_addr = start_addr + (i * sect_size)
            sect = obj.Object("_IMAGE_SECTION_HEADER", offset = s_addr, vm = self.obj_vm,
                              parent = self, native_vm = self.obj_native_vm)
            if not unsafe:
                sect.sanity_check_section()
            yield sect

class _IMAGE_SECTION_HEADER(obj.CType):
    """PE section"""

    def sanity_check_section(self):
        """Sanity checks address boundaries"""
        # Note: all addresses here are RVAs
        image_size = self.obj_parent.OptionalHeader.SizeOfImage
        if self.VirtualAddress > image_size:
            raise ValueError('VirtualAddress {0:08x} is past the end of image.'.format(self.VirtualAddress))
        if self.Misc.VirtualSize > image_size:
            raise ValueError('VirtualSize {0:08x} is larger than image size.'.format(self.Misc.VirtualSize))
        if self.SizeOfRawData > image_size:
            raise ValueError('SizeOfRawData {0:08x} is larger than image size.'.format(self.SizeOfRawData))

class _CM_KEY_BODY(obj.CType):
    """Registry key"""

    def full_key_name(self):
        output = []
        kcb = self.KeyControlBlock
        while kcb.ParentKcb:
            if kcb.NameBlock.Name == None:
                break
            output.append(str(kcb.NameBlock.Name))
            kcb = kcb.ParentKcb
        return "\\".join(reversed(output))

class _MMVAD_FLAGS(obj.CType):
    """This is for _MMVAD_SHORT.u.VadFlags"""
    def __str__(self):
        return ", ".join(["%s: %s" % (name, self.m(name)) for name in sorted(self.members.keys()) if self.m(name) != 0])

class _MMVAD_FLAGS2(_MMVAD_FLAGS):
    """This is for _MMVAD_LONG.u2.VadFlags2"""
    pass

class _MMSECTION_FLAGS(_MMVAD_FLAGS):
    """This is for _CONTROL_AREA.u.Flags"""
    pass


import crash_vtypes
import hibernate_vtypes
import kdbg_vtypes
import tcpip_vtypes
import ssdt_vtypes

class WindowsOverlay(obj.ProfileModification):
    conditions = {'os': lambda x: x == 'windows'}
    before = ['BasicObjectClasses', 'WindowsVTypes']

    def modification(self, profile):
        profile.merge_overlay(windows_overlay)

class WindowsVTypes(obj.ProfileModification):
    conditions = {'os': lambda x: x == 'windows'}
    before = ['BasicObjectClasses']

    def modification(self, profile):
        profile.vtypes.update(crash_vtypes.crash_vtypes)
        profile.vtypes.update(hibernate_vtypes.hibernate_vtypes)
        profile.vtypes.update(kdbg_vtypes.kdbg_vtypes)
        profile.vtypes.update(tcpip_vtypes.tcpip_vtypes)
        profile.vtypes.update(ssdt_vtypes.ssdt_vtypes)

class WindowsObjectClasses(obj.ProfileModification):
    constratints = {'os': lambda x: x == 'windows'}
    before = ['BasicObjectClasses', 'WindowsVTypes', 'WindowsOverlay']

    def modification(self, profile):
        profile.object_classes.update({
            '_UNICODE_STRING': _UNICODE_STRING,
            '_LIST_ENTRY': _LIST_ENTRY,
            'WinTimeStamp': WinTimeStamp,
            '_EPROCESS': _EPROCESS,
            '_ETHREAD': _ETHREAD,
            '_HANDLE_TABLE': _HANDLE_TABLE,
            '_OBJECT_HEADER': _OBJECT_HEADER,
            '_FILE_OBJECT': _FILE_OBJECT,
            '_MMVAD': _MMVAD,
            '_MMVAD_SHORT': _MMVAD_SHORT,
            '_MMVAD_LONG': _MMVAD_LONG,
            '_EX_FAST_REF': _EX_FAST_REF,
            'ThreadCreateTimeStamp': ThreadCreateTimeStamp,
            'IpAddress': IpAddress,
            'VolatilityKPCR': VolatilityKPCR,
            'VolatilityKDBG': VolatilityKDBG,
            'VolatilityIA32ValidAS': VolatilityIA32ValidAS,
            '_IMAGE_DOS_HEADER': _IMAGE_DOS_HEADER,
            '_IMAGE_NT_HEADERS': _IMAGE_NT_HEADERS,
            '_IMAGE_SECTION_HEADER': _IMAGE_SECTION_HEADER,
            '_CM_KEY_BODY': _CM_KEY_BODY,
            '_MMVAD_FLAGS': _MMVAD_FLAGS,
            '_MMVAD_FLAGS2': _MMVAD_FLAGS2,
            '_MMSECTION_FLAGS': _MMSECTION_FLAGS,
            '_TOKEN': _TOKEN,
            })

class AbstractKDBGMod(obj.ProfileModification):
    kdbgsize = 0x290

    def modification(self, profile):
        signature = '\x00\x00\x00\x00\x00\x00\x00\x00' if profile.metadata.get('memory_model', '32bit') == '32bit' else '\x00\xf8\xff\xff'
        signature += 'KDBG' + struct.pack('<H', self.kdbgsize)
        profile.merge_overlay({'VOLATILITY_MAGIC': [ None, {
                                'KDBGHeader': [ None, ['VolatilityMagic', dict(value = signature)]]
                                                            }
                                                    ]})

### DEPRECATED FEATURES ###
#
# These are due from removal after version 2.2,
# please do not rely upon them

class AbstractWindows(obj.Profile):
    """ A Profile for Windows systems """
    _md_os = 'windows'
