#!/usr/bin/env python
#
# File: $Id$
#
"""
Objects and functions to fetch elements of a message.
"""

# system imports
#
# System imports
#
import email.Utils
import os.path
from cStringIO import StringIO
from email.Generator import Generator
from email.Header import Header

# asimap imports
#
import asimap.utils

############################################################################
#
class BadSection(Exception):
    def __init__(self, value = "bad 'section'"):
        self.value = value
    def __str__(self):
        return "BadSection: %s" % self.value

############################################################################
#
class TextGenerator(Generator):
    def __init__(self, outfp, headers = False):
        """
        This is a special purpose message generator.

        We need a generator that can be used to represent the 'TEXT'
        fetch attribute. When used on a multipart message it does not
        render teh headers of the message, but renders the headers of
        every sub-part.

        When used on a message that is not a multipart it just renders
        the body.

        We do this by having the 'clone()' method basically reverse
        whether or nto we should print the headers, and the _write()
        method looks at that instance variable to decide if it should
        print the headers or not.

        outfp is the output file-like object for writing the message to.  It
        must have a write() method.

        """
        Generator.__init__(self, outfp)
        self._headers = headers
    
    def _write(self, msg):
        # Just like the original _write in the Generator class except
        # that we do not write the headers if self._headers is false.
        #
        if self._headers:
            Generator._write(self, msg)
        else:
            self._dispatch(msg)

    def clone(self, fp, headers = True):
        """Clone this generator with the exact same options."""
        return self.__class__(fp, headers)

############################################################################
#
def _is8bitstring(s):
    if isinstance(s, str):
        try:
            unicode(s, 'us-ascii')
        except UnicodeError:
            return True
    return False

############################################################################
#
class HeaderGenerator(Generator):
    
    def __init__(self, outfp, headers = [], skip = True):
        """
        A generator that prints out only headers. If 'skip' is true,
        then headers in the list 'headers' are NOT included in the
        output.

        If skip is False then only headers in the list 'headers' are
        included in the output.

        The default of headers = [] and skip = True will cause all
        headers to be printed.

        NOTE: Headers are compared in a case insensitive fashion so
        'bCc' and 'bCC' and 'bcc' are all the same.
        """
        Generator.__init__(self, outfp)
        self._headers = [x.lower() for x in headers]
        self._skip = skip

    def clone(self, fp):
        """Clone this generator with the exact same options."""
        return self.__class__(fp, self._headers, self._skip)

    def _write(self, msg):
        # Just like the original _write in the Generator class except
        # that we do is write the headers.
        #
        # Write the headers.  First we see if the message object wants to
        # handle that itself.  If not, we'll do it generically.
        #
        # XXX What messages have a headers method? Note that using the
        #     message's '_write_headers' function will skip our header
        #     field exclusion/inclusion rules.
        #
        meth = getattr(msg, '_write_headers', None)
        if meth is None:
            self._write_headers(msg)
        else:
            meth(self)

    def _write_headers(self, msg):
        for h, v in msg.items():
            # Determine if we are supposed to skip this header or not.
            #
            if (self._skip and h.lower() in self._headers) or \
               (not self._skip and h.lower() not in self._headers):
                continue

            # Otherwise output this header.
            #
            print >> self._fp, '%s:' % h,
            if self._maxheaderlen == 0:
                # Explicit no-wrapping
                print >> self._fp, v
            elif isinstance(v, Header):
                # Header instances know what to do
                print >> self._fp, v.encode()
            elif _is8bitstring(v):
                # If we have raw 8bit data in a byte string, we have no idea
                # what the encoding is.  There is no safe way to split this
                # string.  If it's ascii-subset, then we could do a normal
                # ascii split, but if it's multibyte then we could break the
                # string.  There's no way to know so the least harm seems to
                # be to not split the string and risk it being too long.
                print >> self._fp, v
            else:
                # Header's got lots of smarts, so use it.
                print >> self._fp, Header(
                    v, maxlinelen=self._maxheaderlen,
                    header_name=h, continuation_ws='\t').encode()
        # A blank line always separates headers from body
        print >> self._fp

############################################################################
#
class FetchAtt(object):
    """
    This object contains the parsed out elements of a fetch command that
    specify an attribute to pull out of a message.

    It is expected that this will be applied to a Message object
    instance to retrieve the parts of the message that this FetchAtt
    indicates.
    """

    OP_BODY          = 'body'
    OP_BODYSTRUCTURE = 'bodystructure'
    OP_ENVELOPE      = 'envelope'
    OP_FLAGS         = 'flags'
    OP_INTERNALDATE  = 'internaldate'
    OP_RFC822_HEADER = 'rfc822.header'
    OP_RFC822_SIZE   = 'rfc822.size'
    OP_RFC822_TEXT   = 'rfc822.text'
    OP_UID           = 'uid'
    
    #######################################################################
    #
    def __init__(self, attribute, section = None, partial = None,
                 peek = False, ext_data = True, actual_command = None):
        """Fill in the details of our FetchAtt object based on what we parse
        from the given attribute/section/partial.
        """
        self.attribute = attribute
        self.section = section
        self.partial = partial
        self.peek = peek
        self.ext_data = ext_data
        if actual_command is None:
            self.actual_command = self.attribute.upper()
        else:
            self.actual_command = actual_command
            

    #######################################################################
    #
    def __repr__(self):
        return "FetchAtt(%s[%s]<%s>)" % (self.attribute, str(self.section),
                                         str(self.partial))

    def __str__(self):
        result = self.actual_command
        if result == "BODY":
            if self.peek:
                result += ".PEEK"
            if self.section is not None:
                # we need to be careful how we convert HEADER.FIELDS and
                # HEADER.FIELDS.NOT back in to a string.
                #
                result += '[%s]' % '.'.join([str(x).upper() for x in self.section])
            if self.partial:
                result += "<%d.%d>" % (self.partial[0],self.partial[1])
        return result
    
    #######################################################################
    #
    def fetch(self, msg, msg_entry):
        """
        This method applies fetch criteria that this object represents
        to the message and message entry being passed in.

        It returns a tuple.

        The first element of the tuple it returns is a string that is
        approrpriately formated as the body of the FETCH response.

        The second element is a boolean indicating whether or not the
        msg_entry object had any changes in its flags (and thus needs
        to be saved to the database and a flag notify to be sent to
        clients that have this mailbox selected.)

        True indicates that the flags have changed.

        NOTE: In case you are wondering a FETCH of a message can cause
        it to gain a '\Seen' flag.
        """

        # We can easily tell if this is going to change a message's flags.
        # The operation is 'body' and peek is False.
        #
        changed = False
        if self.attribute == self.OP_BODY and self.peek is False and \
                '\Seen' not in msg_entry.flags:
            msg_entry.flags.append('\Seen')
            changed = True

        # Based on the operation figure out what subroutine does the rest
        # of the work.
        #
        if self.attribute  == "body":
            result = self.body(msg, self.section)
        elif self.attribute == "bodystructure":
            result = self.bodystructure(msg)
        elif self.attribute == "envelope":
            result = self.envelope(msg)
        elif self.attribute == "flags":
            result = '(%s)' % ' '.join(msg_entry.flags)
        elif self.attribute == "internaldate":
            result = '"%s"' % asimap.utils.formatdate(msg_entry.internal_date)
        elif self.attribute == "rfc822.size":
            result = str(len(email.Utils.fix_eols(msg.as_string())))
        elif self.attribute == "uid":
            result = str(msg_entry.uid)
        else:
            raise NotImplemented
        
        return ("%s %s" % (str(self), result), changed)

    #######################################################################
    #
    def body(self, msg, section):
        """
        Fetch the appropriate part of the message and return it to the
        user. If 'peek' is false, this will also potentially change
        the /Seen flag on a message (if it is not set already.)
        """

        msg_text = None
        g = None
        if len(section) == 0:
            # They want the entire message.
            #
            # This really only ever is the case as our first invocation of the
            # body() method. All further recursive calls will always have at
            # least one element in the section list when they are called.
            #
            msg_text = msg.as_string()
        else:
            if len(section) == 1:
                fp = StringIO()
                if isinstance(section[0], int):
                    # The want a sub-part. Get that sub-part. Watch
                    # out for messages that are not multipart. You can
                    # get a sub-part of these as long as it is only
                    # sub-part #1.
                    #
                    g = TextGenerator(fp, headers = False)

                    if section[0] == 1 and not msg.is_multipart():
                        # The logic is simpler to read this way.. if
                        # they want section 1 and this message is NOT
                        # a multipart message, then do the same as
                        # 'TEXT'
                        #
                        pass
                    else:
                        # Otherwise, get the sub-part they are after
                        # as the message to pass to the generator.
                        #
                        try: 
                            msg = msg.get_payload(section[0]-1)
                        except TypeError:
                            raise BadSection("Section %d does not exist in "
                                             "this message sub-part" % \
                                             section[0])
                elif section[0] == 'TEXT':
                    g = TextGenerator(fp, headers = False)
                elif isinstance(section[0], list):
                    if section[0][0] == "HEADER.FIELDS":
                        g = HeaderGenerator(fp, headers = section[0][1],
                                            skip = False)
                    elif section[0][0] == "HEADER.FIELDS.NOT":
                        g = HeaderGenerator(fp, headers = section[0][1],
                                            skip = True)
                    else:
                        raise BadSection("Section value must be either "
                                         "HEADER.FIELDS or HEADER.FIELDS.NOT, "
                                         "not: %s" % section[0][0])
                else:
                    g = HeaderGenerator(fp)
                    if section[0] == 'MIME':
                        # XXX just use the generator as it is for MIME.. I know
                        # this is not quite right in that it will accept more
                        # then it should, but it will otherwise work.
                        #
                        pass 
                    elif section[0] == 'HEADER':
                        # if the content type is message/rfc822 then to
                        # get the headers we need to use the first
                        # sub-part of this message.
                        #
                        if msg.is_multipart() and \
                           msg.get_content_type() == 'message/rfc822':
                            msg = msg.get_payload(0)
                    else:
                        raise BadSection("Unexpected section value: %s" % \
                                         section[0])
            elif isinstance(section[0], int):
                # We have an integer sub-section. This means that we
                # need to pull apart the message (it MUST be a
                # multi-part message) and pass to a recursive
                # invocation of this function the sub-part and the
                # section list (with the top element of the section
                # list removed.)
                #
                if not msg.is_multipart():
                    raise BadSection("Message does not contain subsection %d "
                                     "(section list: %s" % section[0],
                                     section)
                try:
                    msg = msg.get_payload(section[0]-1)
                except TypeError:
                    raise BadSection("Message does not contain subsection %d "
                                     "(section list: %s)" % section[0],
                                     section)
                return self.body(msg, section[1:])

            # We should have a generator that will give us the text
            # that we want. If we do not then we were not able to find
            # an appropriate section to parse.
            #
            if g is None:
                raise BadSection("Section selector '%s' can not be parsed" % \
                                 section)
            g.flatten(msg)
            msg_text = fp.getvalue()
        
        # We have our message text we need to return to our caller.
        # truncate if it we also have a 'partial' defined.
        #
        # Convert \n in to \r\n
        #
        msg_text = email.Utils.fix_eols(msg_text)
        if self.partial:
            msg_text = msg_text[self.partial[0]:self.partial[1]]

        # We return all of these body sections as a length prefixed IMAP
        # string.
        #
        return "{%d}\r\n%s" % (len(msg_text), msg_text)

    #######################################################################
    #
    def envelope(self, msg):
        """
        Get the envelope structure of the message as a list, in a defined
        order.

        Any fields that we can not determine the value of are NIL.

        XXX This does not need to be an instance method..

        """
        result = []

        from_field = ""
        for field in ('date', 'subject', 'from', 'sender', 'reply-to',
                      'to', 'cc', 'bcc', 'in-reply-to', 'message-id'):

            # 'reply-to' and 'sender' are copied from the 'from' field
            # if they are not explicitly defined.
            #
            if field in ('sender', 'reply-to') and field not in msg:
                result.append(from_field)
                continue

            # If a field is not in the message it is nil.
            #
            if field not in msg:
                result.append("NIL")
                continue
                
            # The from, sender, reply-to, to, cc, and bcc fields are
            # parenthesized lists of address structures.
            #
            if field in ('from', 'sender', 'reply-to', 'to', 'cc', 'bcc'):
                addrs = email.Utils.getaddresses([msg[field]])
                if len(addrs) == 0:
                    result.append("NIL")
                    continue

                addr_list = []
                for name, paddr in addrs:
                    one_addr = []
                    if name == "":
                        one_addr.append("NIL")
                    else:
                        one_addr.append('"%s"' % name)
                    one_addr.append("NIL")
                    if paddr != "":
                        mbox_name, host_name = paddr.split('@')
                        one_addr.append('"%s"' % mbox_name)
                        one_addr.append('"%s"' % host_name)
                    else:
                        one_addr.append("NIL")
                    addr_list.append("(%s)" % " ".join(one_addr))
                result.append("(%s)" % "".join(addr_list))

                # We stash the from field because we may need it for sender
                # and reply-to
                #
                if field == "from":
                    from_field = result[-1]
            else:
                result.append('"%s"' % msg[field])
        return '(%s)' % " ".join(result)

    #######################################################################
    #
    def bodystructure(self, msg):
        '''
        XXX NOTE: WE need to not send extension data if self.ext_data is False.
        '''

        if msg.is_multipart():
            # If the message is a multipart message then the bodystructure
            # for this multipart is a parenthesized list.
            #
            # The list begins with a parenthesized list that is the
            # bodystructure for each sub-part.
            #
            # Then we have as an imap string the sub-type of the
            # multipart message (ie: 'mixed' 'digest', 'parallel',
            # 'alternative').
            #
            # Following the subtype is the extension data.
            #
            # The extension data appears in the following order:
            #
            # o body parameters as a parenthesized list. The body parameters
            #   are key value pairs (usually things like the multi-part
            #   boundary separator string.)
            #
            # o MD5 - which we do not support so we send back NIL
            #
            # o body disposition: NIL or A parenthesized list, consisting of
            #   a disposition type string followed by a parenthesized list of
            #   disposition attribute/value pairs.  The disposition type and
            #   attribute names will be defined in a future standards-track
            #   revision to [DISPOSITION]. NOTE: This means we always return
            #   NIL as disposition types have not been defined.
            #
            # o body language: A string or parenthesized list giving the body
            #   language value as defined in [LANGUAGE-TAGS].
            #   NOTE: This is also NIL as these are not defined either.
            #
            sub_parts = []
            for sub_part in msg.get_payload():
                sub_parts.append(self.bodystructure(sub_part))

            # If we are NOT supposed to return extension data (ie:
            # doing a 'body' not a 'bodystructure' then we have
            # everything we need to return a result.
            #
            if not self.ext_data:
                return '(%s "%s")' % (''.join(sub_parts),
                                      msg.get_content_subtype().upper())
            
            # Otherwise this is a real 'bodystructure' fetch and we need to
            # return the extension data as well.
            #
            ext_data = []
            for k,v in msg.get_params():
                if v == '':
                    continue
                ext_data.append('"%s"' % k.upper())
                ext_data.append('"%s"' % v)

            # The 'nil nil nil' at the end are md5, content disposition, lang
            # which are not set for a container.
            #
            return '(%s "%s" (%s) NIL NIL NIL)' % \
                   (''.join(sub_parts),
                    msg.get_content_subtype().upper(),
                    ' '.join(ext_data))

        # Otherwise, we figure out the bodystructure of this message
        # part and return that as a string in parentheses.
        #
        # Consult the FETCH response section of rfc2060 for the gory
        # details of how and why the list is formatted this way.
        #
        result = []

        # Body type and sub-type
        #
        result.append('"%s"' % msg.get_content_maintype().upper())
        result.append('"%s"' % msg.get_content_subtype().upper())

        # Parenthesized list of the message parameters as a list of
        # key followed by value.
        #
        params = []
        for k,v in msg.get_params():
            if v == '':
                continue
            params.append('"%s"' % k.upper())
            params.append('"%s"' % v)

        if len(params) > 0:
            result.append('(%s)' % ' '.join(params))
        else:
            # If we have no parameters we force assumption of
            # 'charset' 'us-ascii'
            #
            result.append('("CHARSET" "US-ASCII")')

        # The body id (what is this? none of our message from a test
        # IMAP server ever set this.
        #
        result.append('NIL')

        # Body description.
        # diito as body id.. noone seems to use this.
        #
        result.append('NIL')

        # The body encoding, from the 'content transfer-encoding' header.
        #
        if 'content-transfer-encoding' in msg:
            result.append('"%s"' % msg['content-transfer-encoding'].upper())
        else:
            result.append('"7BIT"')

        # Body size.. length of the payload string.
        #
        # NOTE: The message payload as returned by the email module has '\n's
        # instead of '\n\r' for newlines. This is probably just coming from
        # the file system directly, but I believe that we need to convert
        # this to \r\n and this needs to figure in our calculation of the
        # number of octets in the message.
        #
        payload = msg.get_payload()
        # XXX move to fixeol's over replace?
        result.append(str(len(payload.replace('\n','\n\r'))))

        # Now come the variable fields depending on the maintype/subtype
        # of this message.
        #
        if msg.get_content_type() == "message/rfc822":
            # envelope structure
            # body structure
            # size in text lines of encapsulated message
            result.append(self.envelope(msg))
            result.append(self.bodystructure(payload))
            result.append(str(len(payload.splitlines())))
        elif msg.get_content_maintype() == "text":
            # size in text lines of the body.
            #
            result.append(str(len(payload.splitlines())))

        # If we are not supposed to return extension data then we are done here.
        #
        if not self.ext_data:
            return '(%s)' % ' '.join(result)

        # Now we have the message body extension data.
        #

        # We do not do MD5..
        result.append('NIL')

        # If we have a content-disposition
        #
        if 'content-disposition' in msg:
            # XXX We are hard coding what we assume will be in
            # XXX content-disposition. This is doomed to eventual failure.
            #
            cd = msg.get_params(header='content-disposition')

            # if the content disposition does not have parameters then just
            # put 'NIL' for the parameter list, otherwise we have a list of
            # key/value pairs for the disposition list.
            #
            if len(cd) == 1:
                result.append('("%s" NIL)' % cd[0][0].upper())
            else:
                cdpl = []
                for k,v in cd[1:]:
                    cdpl.extend(['"%s" "%s"' % (k.upper(),v)])
                result.append('("%s" (%s))' % (cd[0][0].upper(),
                                               " ".join(cdpl)))
        else:
            result.append('NIL')

        # And body language.. which we always set to NIL for now.
        #
        result.append('NIL')

        # IMAP servers we compared with add an additional extension data, but
        # it was always NIL. So we will add this to for the sake of returning
        # the same output as them. Since it was always NIL and clients MUST
        # accept additional data this should cause no problems. Eventually I
        # will find out which RFC defines this and what it should actually
        # be.
        #
        result.append('NIL')

        # Convert our result in to a parentheses list.
        #
        return '(%s)' % ' '.join(result)