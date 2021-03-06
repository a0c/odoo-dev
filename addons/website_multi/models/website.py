import openerp
from openerp import SUPERUSER_ID
from openerp.osv import orm, fields, osv
from openerp.addons.website.models.website import slugify
from openerp.addons.web.http import request
from werkzeug.exceptions import NotFound


class website(orm.Model):

    _inherit = "website"

    def _get_menu_website(self, cr, uid, ids, context=None):
        res = []
        for menu in self.pool.get('website.menu').browse(cr, uid, ids, context=context):
            if menu.website_id:
                res.append(menu.website_id.id)
        # IF a menu is changed, update all websites
        return res

    def _get_menu(self, cr, uid, ids, name, arg, context=None):
        result = {}
        menu_obj = self.pool['website.menu']

        for website_id in ids:
            menu_ids = menu_obj.search(cr, uid, [
                ('parent_id', '=', False),
                ('website_id', '=', website_id),
            ], order='id', context=context)
            result[website_id] = menu_ids and menu_ids[0] or False

        return result

    _columns = {
        'menu_id': fields.function(
            _get_menu,
            relation='website.menu',
            type='many2one',
            string='Main Menu',
            store={
                'website.menu': (_get_menu_website, ['sequence', 'parent_id', 'website_id'], 10)
            }
        )
    }

    _defaults = {
        'user_id': lambda s, c, u, x: s.pool['ir.model.data'].xmlid_to_res_id(c, SUPERUSER_ID, 'base.public_user'),
        'company_id': lambda s, c, u, x: s.pool['ir.model.data'].xmlid_to_res_id(c, SUPERUSER_ID, 'base.main_company'),
    }

    def new_page(self, cr, uid, name, template='website.default_page', ispage=True, context=None):
        context = context or {}
        imd = self.pool['ir.model.data']
        view = self.pool['ir.ui.view']
        template_module, template_name = template.split('.')

        # completely arbitrary max_length
        page_name = slugify(name, max_length=50)
        page_xmlid = "%s.%s" % (template_module, page_name)

        try:
            # existing page
            imd.get_object_reference(cr, uid, template_module, page_name)
        except ValueError:
            # new page
            _, template_id = imd.get_object_reference(cr, uid, template_module, template_name)

            page_id = view.copy(cr, uid, template_id, {
                'website_id': context.get('website_id'),
                'key': page_xmlid
            }, context=context)

            page = view.browse(cr, uid, page_id, context=context)

            page.write({
                'arch': page.arch.replace(template, page_xmlid),
                'name': page_name,
                'page': ispage,
            })

        return page_xmlid

    @openerp.tools.ormcache(skiparg=4)
    def _get_current_website_id(self, cr, uid, domain_name, context=None):
        website_id = 1
        ids = self.search(cr, uid, [
            ('name', '=', domain_name)
        ], context=context)
        if ids:
            website_id = ids[0]
        return website_id

    def get_current_website(self, cr, uid, context=None):
        domain_name = request.httprequest.environ.get('HTTP_HOST', '').split(':')[0]
        website_id = self._get_current_website_id(cr, uid, domain_name, context=context)
        request.context['website_id'] = website_id
        return self.browse(cr, uid, website_id, context=context)

    def get_template(self, cr, uid, ids, template, context=None):
        View = self.pool['ir.ui.view']
        if isinstance(template, (int, long)):
            view_id = template
        else:
            if '.' not in template:
                template = 'website.%s' % template
            view_id = View.get_view_id(cr, uid, template, context=context)
            if not view_id:
                raise NotFound
        return View.browse(cr, uid, view_id, context=context)


class ir_http(osv.AbstractModel):
    _inherit = 'ir.http'

    def _auth_method_public(self):
        if not request.session.uid:
            if request.website and request.website.user_id:
                request.uid = request.website.user_id.id
            else:
                domain_name = request.httprequest.host
                website_id = self.pool['website']._get_current_website_id(request.cr, SUPERUSER_ID, domain_name)
                if website_id:
                    uid = self.pool['website'].read(request.cr, SUPERUSER_ID, website_id, ['user_id'], load='_classic_write')['user_id']
                    if uid:
                        request.uid = uid
                        return
                dummy, request.uid = self.pool['ir.model.data'].get_object_reference(request.cr, openerp.SUPERUSER_ID, 'base', 'public_user')
        else:
            request.uid = request.session.uid
