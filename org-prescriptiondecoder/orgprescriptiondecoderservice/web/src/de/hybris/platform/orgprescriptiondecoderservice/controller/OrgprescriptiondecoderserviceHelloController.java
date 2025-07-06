/*
 * Copyright (c) 2021 SAP SE or an SAP affiliate company. All rights reserved.
 */
package de.hybris.platform.orgprescriptiondecoderservice.controller;

import static de.hybris.platform.orgprescriptiondecoderservice.constants.OrgprescriptiondecoderserviceConstants.PLATFORM_LOGO_CODE;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Controller;
import org.springframework.ui.ModelMap;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;

import de.hybris.platform.orgprescriptiondecoderservice.service.OrgprescriptiondecoderserviceService;


@Controller
public class OrgprescriptiondecoderserviceHelloController
{
	@Autowired
	private OrgprescriptiondecoderserviceService orgprescriptiondecoderserviceService;

	@RequestMapping(value = "/", method = RequestMethod.GET)
	public String printWelcome(final ModelMap model)
	{
		model.addAttribute("logoUrl", orgprescriptiondecoderserviceService.getHybrisLogoUrl(PLATFORM_LOGO_CODE));
		return "welcome";
	}
}
