import logging
from lxml import etree

from openerp import tools
from openerp.osv import osv, fields
from openerp.tools.parse_version import parse_version
from openerp.tools.view_validation import valid_view

_logger = logging.getLogger(__name__)


class view(osv.osv):

    _inherit = "ir.ui.view"

    _columns = {
        'website_id': fields.many2one('website', ondelete='cascade', string="Website", copy=False),
        'key': fields.char('Key')
    }

    _sql_constraints = [(
        'key_website_id_unique',
        'unique(key, website_id)',
        'Key must be unique per website.'
    )]

    @tools.ormcache_context(accepted_keys=('website_id',))
    def get_view_id(self, cr, uid, xml_id, context=None):
        if context and 'website_id' in context and not isinstance(xml_id, (int, long)):
            domain = [
                ('key', '=', xml_id),
                '|',
                ('website_id', '=', context['website_id']),
                ('website_id', '=', False)
            ]
            xml_ids = self.search(cr, uid, domain, order='website_id', limit=1, context=context)
            if not xml_ids:
                xml_id = self.pool['ir.model.data'].xmlid_to_res_id(cr, uid, xml_id, raise_if_not_found=True)
                if self.read(cr, uid, xml_id, ['page'], context=context)['page']:
                    raise ValueError('Invalid template id: %r' % (xml_id,))
            else:
                xml_id = xml_ids[0]
        else:
            xml_id = self.pool['ir.model.data'].xmlid_to_res_id(cr, uid, xml_id, raise_if_not_found=True)
        return xml_id

    _read_template_cache = dict(accepted_keys=('lang', 'inherit_branding', 'editable', 'translatable', 'website_id'))

    @tools.ormcache_context(**_read_template_cache)
    def _read_template(self, cr, uid, view_id, context=None):
        arch = self.read_combined(cr, uid, view_id, fields=['arch'], context=context)['arch']
        arch_tree = etree.fromstring(arch)

        if 'lang' in context:
            arch_tree = self.translate_qweb(cr, uid, view_id, arch_tree, context['lang'], context)

        self.distribute_branding(arch_tree)
        root = etree.Element('templates')
        root.append(arch_tree)
        arch = etree.tostring(root, encoding='utf-8', xml_declaration=True)
        return arch

    @tools.ormcache(size=0)
    def read_template(self, cr, uid, xml_id, context=None):
        if isinstance(xml_id, (int, long)):
            view_id = xml_id
        else:
            if '.' not in xml_id:
                raise ValueError('Invalid template id: %r' % (xml_id,))
            view_id = self.get_view_id(cr, uid, xml_id, context=context)
        return self._read_template(cr, uid, view_id, context=context)

    def clear_cache(self):
        self._read_template.clear_cache(self)
        self.get_view_id.clear_cache(self)
        
    def get_inheriting_views_arch(self, cr, uid, view_id, model, context=None):
        arch = super(view, self).get_inheriting_views_arch(cr, uid, view_id, model, context=context)
        to_skip = set()
        if context and 'website_id' in context:
            for view_rec in self.browse(cr, 1, [v for a, v in arch], context):
                if view_rec.website_id and view_rec.website_id.id != context['website_id']:
                    to_skip.add(view_rec.id)
        return filter(lambda (a, v): v not in to_skip, arch)

    def _check_xml(self, cr, uid, ids, context=None):
        if context is None:
            context = {}
        context = dict(context, check_view_ids=ids)

        # Sanity checks: the view should not break anything upon rendering!
        # Any exception raised below will cause a transaction rollback.
        for view in self.browse(cr, uid, ids, context):
            if view.website_id:
                context['website_id'] = view.website_id.id
            view_def = self.read_combined(cr, uid, view.id, ['arch'], context=context)
            view_arch_utf8 = view_def['arch']
            if view.type != 'qweb':
                view_doc = etree.fromstring(view_arch_utf8)
                # verify that all fields used are valid, etc.
                self.postprocess_and_fields(cr, uid, view.model, view_doc, view.id, context=context)
                # RNG-based validation is not possible anymore with 7.0 forms
                view_docs = [view_doc]
                if view_docs[0].tag == 'data':
                    # A <data> element is a wrapper for multiple root nodes
                    view_docs = view_docs[0]
                validator = self._relaxng()
                for view_arch in view_docs:
                    version = view_arch.get('version', '7.0')
                    if parse_version(version) < parse_version('7.0') and validator and not validator.validate(view_arch):
                        for error in validator.error_log:
                            _logger.error(tools.ustr(error))
                        return False
                    if not valid_view(view_arch):
                        return False
        return True

    _constraints = [
        (_check_xml, 'Invalid view definition', ['arch']),
    ]
