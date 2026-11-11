import unittest
from html.parser import HTMLParser

from app.routes import _render_ad_from_payload


class Anchors(HTMLParser):
    def __init__(self, html):
        super().__init__(); self.ads=[]; self.feed(html)

    def handle_starttag(self, tag, attrs):
        values=dict(attrs)
        if tag=='a': self.ads.append(values)


class BannerMetadataTests(unittest.TestCase):
    def payload(self, **overrides):
        return {'banners':[{'title':'Campanha Câmara', 'image':'/media/campanha.gif',
                            'link':'https://cliente.example/', **overrides}]}

    def test_stable_creative_identity_and_separate_placement(self):
        top=Anchors(_render_ad_from_payload('header_top',self.payload())).ads[0]
        middle=Anchors(_render_ad_from_payload('home_top_left',self.payload())).ads[0]
        self.assertEqual(top['data-ad-promotion-id'],middle['data-ad-promotion-id'])
        self.assertRegex(top['data-ad-promotion-id'],r'^trivox-[a-f0-9]{20}$')
        self.assertEqual(top['data-ad-placement'],'Topo / Cabeçalho')
        self.assertEqual(middle['data-ad-placement'],'Meio / Esquerda')
        for changed in [self.payload(image='/media/nova.gif'),self.payload(title='Nova campanha')]:
            other=Anchors(_render_ad_from_payload('header_top',changed)).ads[0]
            self.assertNotEqual(top['data-ad-promotion-id'],other['data-ad-promotion-id'])

    def test_attribute_values_are_escaped_and_no_destination_sent_as_metadata(self):
        title='Campanha " <Teste> & Cliente'
        ad=Anchors(_render_ad_from_payload('sidebar_1',self.payload(title=title))).ads[0]
        self.assertEqual(ad['data-ad-promotion-name'],title)
        self.assertFalse(any('cliente.example' in (v or '') for k,v in ad.items() if k.startswith('data-')))
        self.assertNotIn('onclick',ad)

    def test_empty_and_invalid_banners_are_not_measured(self):
        self.assertEqual(_render_ad_from_payload('header_top',{'banners':[None,{}, {'image':''}]}),'')

    def test_rotation_and_links_keep_existing_behavior(self):
        data=self.payload();data['banners']*=2;data['interval_seconds']=7
        html=_render_ad_from_payload('sidebar_1',data);ads=Anchors(html).ads
        self.assertIn('data-ad-interval="7000"',html)
        self.assertEqual(len(ads),2)
        self.assertNotIn('hidden',ads[0]);self.assertIn('hidden',ads[1])
        self.assertTrue(all(ad['target']=='_blank' and ad['href']=='https://cliente.example/' for ad in ads))


if __name__=='__main__':unittest.main()
