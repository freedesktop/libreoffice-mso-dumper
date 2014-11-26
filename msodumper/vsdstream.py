#!/usr/bin/env python2
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#

import ole
import ctypes
import struct
from docdirstream import DOCDirStream
import docrecord
import globals
import sys
import os
import bisect


class VSDFile:
    """Represents the whole visio file - feed will all bytes."""
    def __init__(self, chars, params):
        self.chars = chars
        self.size = len(self.chars)
        self.params = params
        self.error = None

        self.init()

    def init(self):
        self.header = ole.Header(self.chars, self.params)
        self.pos = self.header.parse()

    def __getDirectoryObj(self):
        obj = self.header.getDirectory()
        obj.parseDirEntries()
        return obj

    def getDirectoryNames(self):
        return self.__getDirectoryObj().getDirectoryNames()

    def getDirectoryStreamByName(self, name):
        obj = self.__getDirectoryObj()
        bytes = obj.getRawStreamByName(name)
        return self.getStreamFromBytes(name, bytes)

    def getStreamFromBytes(self, name, bytes):
        if name == "\x05SummaryInformation":
            return SummaryInformationStream(bytes, self.params, doc=self)
        else:
            return DOCDirStream(bytes, self.params, name, doc=self)

    def getName(self):
        return "native"


class GsfVSDFile(VSDFile):
    """Same as VSDFile, but uses gsf to read the OLE streams."""
    def __init__(self, chars, params, gsf):
        self.gsf = gsf
        VSDFile.__init__(self, chars, params)

    def disableStderr(self):
        nil = os.open(os.devnull, os.O_WRONLY)
        self.savedStderr = os.dup(2)
        os.dup2(nil, 2)

    def enableStderr(self):
        os.dup2(self.savedStderr, 2)

    def init(self):
        self.streams = {}
        self.gsf.gsf_init()
        gsfInput = self.gsf.gsf_input_memory_new(self.chars, len(self.chars), False)
        self.disableStderr()
        gsfInfile = self.gsf.gsf_infile_msole_new(gsfInput, None)
        self.enableStderr()
        if not gsfInfile:
            self.error = "gsf_infile_msole_new() failed"
            return
        for i in range(self.gsf.gsf_infile_num_children(gsfInfile)):
            child = self.gsf.gsf_infile_child_by_index(gsfInfile, i)
            childName = ctypes.string_at(self.gsf.gsf_infile_name_by_index(gsfInfile, i))
            childSize = self.gsf.gsf_input_size(child)
            childData = ""
            while True:
                bufSize = 1024
                pos = self.gsf.gsf_input_tell(child)
                if pos == childSize:
                    break
                elif pos + bufSize > childSize:
                    bufSize = childSize - pos
                childData += ctypes.string_at(self.gsf.gsf_input_read(child, bufSize, None), bufSize)
            self.streams[childName] = childData
        self.gsf.gsf_shutdown()

    def getDirectoryNames(self):
        return self.streams.keys()

    def getDirectoryStreamByName(self, name):
        return self.getStreamFromBytes(name, self.streams[name])

    def getName(self):
        return "gsf"


def createVSDFile(chars, params):
    hasGsf = True
    try:
        gsf = ctypes.cdll.LoadLibrary('libgsf-1.so')
        gsf.gsf_input_read.restype = ctypes.c_void_p
    except:
        hasGsf = False

    if hasGsf:
        return GsfVSDFile(chars, params, gsf)
    else:
        return VSDFile(chars, params)


class SummaryInformationStream(DOCDirStream):
    def __init__(self, bytes, params, doc):
        DOCDirStream.__init__(self, bytes, params, "\x05SummaryInformation", doc=doc)

    def dump(self):
        print '<stream name="\\x05SummaryInformation" size="%d">' % self.size
        PropertySetStream(self).dump()
        print '</stream>'


class PropertySetStream(DOCDirStream):
    def __init__(self, parent):
        DOCDirStream.__init__(self, parent.bytes)
        self.parent = parent

    def dump(self):
        print '<propertySetStream type="PropertySetStream" offset="%s">' % self.pos
        self.printAndSet("ByteOrder", self.readuInt16())
        self.printAndSet("Version", self.readuInt16())
        self.printAndSet("SystemIdentifier", self.readuInt32())
        self.printAndSet("CLSID0", self.readuInt32())
        self.printAndSet("CLSID1", self.readuInt32())
        self.printAndSet("CLSID2", self.readuInt32())
        self.printAndSet("CLSID3", self.readuInt32())
        self.printAndSet("NumPropertySets", self.readuInt32())
        self.printAndSet("FMTID00", self.readuInt32())
        self.printAndSet("FMTID01", self.readuInt32())
        self.printAndSet("FMTID02", self.readuInt32())
        self.printAndSet("FMTID03", self.readuInt32())
        self.printAndSet("Offset0", self.readuInt32())
        if self.NumPropertySets == 0x00000002:
            print '<todo what="PropertySetStream::dump: handle NumPropertySets == 0x00000002"/>'
        PropertySet(self).dump()
        print '</propertySetStream>'


class PropertySet(DOCDirStream):
    def __init__(self, parent):
        DOCDirStream.__init__(self, parent.bytes)
        self.parent = parent
        self.pos = parent.Offset0

    def getCodePage(self):
        for index, idAndOffset in enumerate(self.idsAndOffsets):
            if idAndOffset.PropertyIdentifier == 0x00000001:  # CODEPAGE_PROPERTY_IDENTIFIER
                return self.typedPropertyValues[index].Value

    def dump(self):
        self.posOrig = self.pos
        print '<propertySet type="PropertySet" offset="%s">' % self.pos
        self.printAndSet("Size", self.readuInt32())
        self.printAndSet("NumProperties", self.readuInt32())
        self.idsAndOffsets = []
        for i in range(self.NumProperties):
            idAndOffset = PropertyIdentifierAndOffset(self, i)
            idAndOffset.dump()
            self.idsAndOffsets.append(idAndOffset)
        self.typedPropertyValues = []
        for i in range(self.NumProperties):
            typedPropertyValue = TypedPropertyValue(self, i)
            typedPropertyValue.dump()
            self.typedPropertyValues.append(typedPropertyValue)
        print '</propertySet>'

PropertyIdentifier = {
    0x00000001: "CODEPAGE_PROPERTY_IDENTIFIER",
    0x00000002: "PIDSI_TITLE",
    0x00000003: "PIDSI_SUBJECT",
    0x00000004: "PIDSI_AUTHOR",
    0x00000005: "PIDSI_KEYWORDS",
    0x00000006: "PIDSI_COMMENTS",
    0x00000007: "PIDSI_TEMPLATE",
    0x00000008: "PIDSI_LASTAUTHOR",
    0x00000009: "PIDSI_REVNUMBER",
    0x0000000A: "PIDSI_EDITTIME",
    0x0000000B: "PIDSI_LASTPRINTED",
    0x0000000C: "PIDSI_CREATE_DTM",
    0x0000000D: "PIDSI_LASTSAVE_DTM",
    0x0000000E: "PIDSI_PAGECOUNT",
    0x0000000F: "PIDSI_WORDCOUNT",
    0x00000010: "PIDSI_CHARCOUNT",
    0x00000011: "PIDSI_THUMBNAIL",
    0x00000012: "PIDSI_APPNAME",
    0x00000013: "PIDSI_DOC_SECURITY",
}


class PropertyIdentifierAndOffset(DOCDirStream):
    def __init__(self, parent, index):
        DOCDirStream.__init__(self, parent.bytes)
        self.parent = parent
        self.index = index
        self.pos = parent.pos

    def dump(self):
        print '<propertyIdentifierAndOffset%s type="PropertyIdentifierAndOffset" offset="%s">' % (self.index, self.pos)
        self.printAndSet("PropertyIdentifier", self.readuInt32(), dict=PropertyIdentifier)
        self.printAndSet("Offset", self.readuInt32())
        print '</propertyIdentifierAndOffset%s>' % self.index
        self.parent.pos = self.pos

PropertyType = {
    0x0000: "VT_EMPTY",
    0x0001: "VT_NULL",
    0x0002: "VT_I2",
    0x0003: "VT_I4",
    0x0004: "VT_R4",
    0x0005: "VT_R8",
    0x0006: "VT_CY",
    0x0007: "VT_DATE",
    0x0008: "VT_BSTR",
    0x000A: "VT_ERROR",
    0x000B: "VT_BOOL",
    0x000E: "VT_DECIMAL",
    0x0010: "VT_I1",
    0x0011: "VT_UI1",
    0x0012: "VT_UI2",
    0x0013: "VT_UI4",
    0x0014: "VT_I8",
    0x0015: "VT_UI8",
    0x0016: "VT_INT",
    0x0017: "VT_UINT",
    0x001E: "VT_LPSTR",
    0x001F: "VT_LPWSTR",
    0x0040: "VT_FILETIME",
    0x0041: "VT_BLOB",
    0x0042: "VT_STREAM",
    0x0043: "VT_STORAGE",
    0x0044: "VT_STREAMED_Object",
    0x0045: "VT_STORED_Object",
    0x0046: "VT_BLOB_Object",
    0x0047: "VT_CF",
    0x0048: "VT_CLSID",
    0x0049: "VT_VERSIONED_STREAM",
}


class TypedPropertyValue(DOCDirStream):
    def __init__(self, parent, index):
        DOCDirStream.__init__(self, parent.bytes)
        self.parent = parent
        self.index = index
        self.pos = parent.posOrig + parent.idsAndOffsets[index].Offset

    def dump(self):
        print '<typedPropertyValue%s type="TypedPropertyValue" offset="%s">' % (self.index, self.pos)
        self.printAndSet("Type", self.readuInt16(), dict=PropertyType)
        self.printAndSet("Padding", self.readuInt16())
        if self.Type == 0x0002:  # VT_I2
            self.printAndSet("Value", self.readInt16())
        elif self.Type == 0x001E:  # VT_LPSTR
            CodePageString(self, "Value").dump()
        else:
            print '<todo what="TypedPropertyValue::dump: unhandled Type %s"/>' % hex(self.Type)
        print '</typedPropertyValue%s>' % self.index


class CodePageString(DOCDirStream):
    def __init__(self, parent, name):
        DOCDirStream.__init__(self, parent.bytes)
        self.pos = parent.pos
        self.parent = parent
        self.name = name

    def dump(self):
        print '<%s type="CodePageString">' % self.name
        self.printAndSet("Size", self.readuInt32())
        bytes = []
        for i in range(self.Size):
            c = self.readuInt8()
            if c == 0:
                break
            bytes.append(c)
        codepage = self.parent.parent.getCodePage()
        if codepage < 0:
            codepage += 2 ** 16  # signed -> unsigned
        encoding = ""
        if codepage == 1252:
            # http://msdn.microsoft.com/en-us/goglobal/bb964654
            encoding = "latin1"
        elif codepage == 65001:
            # http://msdn.microsoft.com/en-us/library/windows/desktop/dd374130%28v=vs.85%29.aspx
            encoding = "utf-8"
        if len(encoding):
            print '<Characters value="%s"/>' % "".join(map(lambda c: chr(c), bytes)).decode(encoding).encode('utf-8')
        else:
            print '<todo what="CodePageString::dump: unhandled codepage %s"/>' % codepage
        print '</%s>' % self.name

# vim:set filetype=python shiftwidth=4 softtabstop=4 expandtab:
